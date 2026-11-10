"""Read-only document listing and processing-status HTTP Lambda."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any
from urllib.parse import unquote

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)

DOCUMENT_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
STATUS_KEY_PATTERN = re.compile(
    r"^processing/([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12})/status\.json$"
)
MAX_STATUS_BYTES = 64 * 1024
MAX_DOCUMENTS = 100

_s3_client: Any | None = None


class DocumentRequestError(ValueError):
    """A document API request is invalid or references an unknown document."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _get_s3_client() -> Any:
    global _s3_client
    if _s3_client is None:
        import boto3

        _s3_client = boto3.client("s3")
    return _s3_client


def _log(event_name: str, **details: Any) -> None:
    LOGGER.info(json.dumps({"event": event_name, **details}, separators=(",", ":")))


def _response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        "body": json.dumps(body, ensure_ascii=False, separators=(",", ":")),
    }


def _read_status(s3_client: Any, *, bucket: str, document_id: str) -> dict[str, Any]:
    key = f"processing/{document_id}/status.json"
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
    except Exception as error:
        error_code = getattr(error, "response", {}).get("Error", {}).get("Code")
        if error_code in {"NoSuchKey", "404"}:
            raise DocumentRequestError(404, "DOCUMENT_NOT_FOUND", "Document was not found.") from error
        raise
    content_length = response.get("ContentLength")
    if (
        not isinstance(content_length, int)
        or content_length < 1
        or content_length > MAX_STATUS_BYTES
    ):
        raise RuntimeError("Document status has an invalid size.")
    body = response["Body"].read(MAX_STATUS_BYTES + 1)
    try:
        status = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("Document status is not valid JSON.") from error
    if (
        not isinstance(status, dict)
        or status.get("schemaVersion") != 1
        or status.get("documentId") != document_id
        or not isinstance(status.get("status"), str)
    ):
        raise RuntimeError("Document status has an invalid schema.")
    return status


def _filename(s3_client: Any, *, bucket: str, document_id: str) -> str:
    try:
        response = s3_client.head_object(
            Bucket=bucket, Key=f"uploads/{document_id}/document.pdf"
        )
        encoded = response.get("Metadata", {}).get("original-filename", "document.pdf")
        filename = unquote(encoded)
        return filename[:128] if filename else "document.pdf"
    except Exception:
        return "document.pdf"


def _public_document(status: dict[str, Any], filename: str) -> dict[str, Any]:
    result = {
        "documentId": status["documentId"],
        "filename": filename,
        "status": status["status"],
        "updatedAt": status.get("updatedAt"),
    }
    for field in ("pageCount", "chunkCount", "characterCount", "indexName"):
        if field in status:
            result[field] = status[field]
    if status.get("status") == "FAILED" and isinstance(status.get("error"), dict):
        result["error"] = {
            "code": status["error"].get("code", "PROCESSING_FAILED"),
            "message": status["error"].get("message", "Document processing failed."),
        }
    return result


def _list_documents(s3_client: Any, *, bucket: str) -> list[dict[str, Any]]:
    response = s3_client.list_objects_v2(Bucket=bucket, Prefix="processing/", MaxKeys=1_000)
    document_ids: list[str] = []
    for item in response.get("Contents", []):
        key = item.get("Key") if isinstance(item, dict) else None
        match = STATUS_KEY_PATTERN.fullmatch(key or "")
        if match and match.group(1) not in document_ids:
            document_ids.append(match.group(1))
        if len(document_ids) >= MAX_DOCUMENTS:
            break

    documents = []
    for document_id in document_ids:
        status = _read_status(s3_client, bucket=bucket, document_id=document_id)
        documents.append(
            _public_document(
                status,
                _filename(s3_client, bucket=bucket, document_id=document_id),
            )
        )
    documents.sort(key=lambda item: item.get("updatedAt") or "", reverse=True)
    return documents


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """List documents or return one document's status."""
    request_id = getattr(context, "aws_request_id", "local")
    try:
        method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
        if method != "GET":
            raise DocumentRequestError(405, "METHOD_NOT_ALLOWED", "Method is not allowed.")
        bucket = os.environ["DOCUMENTS_BUCKET_NAME"]
        document_id = event.get("pathParameters", {}).get("documentId")
        if document_id is None:
            documents = _list_documents(_get_s3_client(), bucket=bucket)
            _log("documents_listed", request_id=request_id, document_count=len(documents))
            return _response(200, {"documents": documents, "count": len(documents)})
        if not isinstance(document_id, str) or not DOCUMENT_ID_PATTERN.fullmatch(document_id):
            raise DocumentRequestError(400, "INVALID_DOCUMENT_ID", "Document ID is invalid.")
        status = _read_status(_get_s3_client(), bucket=bucket, document_id=document_id)
        document = _public_document(
            status,
            _filename(_get_s3_client(), bucket=bucket, document_id=document_id),
        )
        _log("document_status_read", request_id=request_id, document_id=document_id)
        return _response(200, document)
    except DocumentRequestError as error:
        _log("document_request_rejected", request_id=request_id, error_code=error.code)
        return _response(
            error.status_code,
            {"error": {"code": error.code, "message": error.message}},
        )
    except KeyError as error:
        _log("document_configuration_error", request_id=request_id)
        return _response(
            500,
            {
                "error": {
                    "code": "CONFIGURATION_ERROR",
                    "message": "The document service is not configured correctly.",
                }
            },
        )
    except Exception as error:
        _log("document_service_error", request_id=request_id, error_type=type(error).__name__)
        return _response(
            502,
            {
                "error": {
                    "code": "STORAGE_ERROR",
                    "message": "Document status is temporarily unavailable.",
                }
            },
        )
