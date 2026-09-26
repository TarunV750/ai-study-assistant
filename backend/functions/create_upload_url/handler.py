"""Create a constrained S3 presigned POST for one PDF upload."""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)

PDF_CONTENT_TYPE = "application/pdf"
DEFAULT_MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024
DEFAULT_EXPIRATION_SECONDS = 300
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

_s3_client: Any | None = None


class RequestValidationError(ValueError):
    """A client request failed validation."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


def _get_s3_client() -> Any:
    global _s3_client
    if _s3_client is None:
        import boto3

        _s3_client = boto3.client("s3")
    return _s3_client


def _json_response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, separators=(",", ":")),
    }


def _log(event_name: str, **details: Any) -> None:
    LOGGER.info(json.dumps({"event": event_name, **details}, separators=(",", ":")))


def _parse_body(event: dict[str, Any]) -> dict[str, Any]:
    if event.get("isBase64Encoded"):
        raise RequestValidationError("body", "Base64-encoded request bodies are not supported.")

    body = event.get("body", event)
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError as error:
            raise RequestValidationError("body", "Request body must be valid JSON.") from error

    if not isinstance(body, dict):
        raise RequestValidationError("body", "Request body must be a JSON object.")
    return body


def _validate_request(payload: dict[str, Any], max_size_bytes: int) -> dict[str, Any]:
    filename = payload.get("filename")
    if not isinstance(filename, str) or not filename.strip():
        raise RequestValidationError("filename", "A filename is required.")
    filename = filename.strip()
    if len(filename) > 128:
        raise RequestValidationError("filename", "Filename must be 128 characters or fewer.")
    if "/" in filename or "\\" in filename or any(ord(char) < 32 for char in filename):
        raise RequestValidationError("filename", "Filename cannot contain paths or control characters.")
    if not filename.lower().endswith(".pdf"):
        raise RequestValidationError("filename", "Only .pdf files are supported.")

    encoded_filename = quote(filename, safe="")
    if len(encoded_filename.encode("ascii")) > 512:
        raise RequestValidationError("filename", "Encoded filename is too long.")

    content_type = payload.get("contentType")
    if content_type != PDF_CONTENT_TYPE:
        raise RequestValidationError("contentType", "Content type must be application/pdf.")

    file_size = payload.get("fileSize")
    if isinstance(file_size, bool) or not isinstance(file_size, int):
        raise RequestValidationError("fileSize", "File size must be an integer number of bytes.")
    if file_size < 1 or file_size > max_size_bytes:
        raise RequestValidationError(
            "fileSize", f"File size must be between 1 and {max_size_bytes} bytes."
        )

    session_id = payload.get("sessionId", "anonymous")
    if not isinstance(session_id, str) or not SESSION_ID_PATTERN.fullmatch(session_id):
        raise RequestValidationError(
            "sessionId", "Session ID may contain 1-64 letters, numbers, underscores, or hyphens."
        )

    return {
        "filename": filename,
        "encoded_filename": encoded_filename,
        "content_type": content_type,
        "file_size": file_size,
        "session_id": session_id,
    }


def _create_upload(
    request: dict[str, Any],
    *,
    bucket_name: str,
    max_size_bytes: int,
    expiration_seconds: int,
) -> dict[str, Any]:
    document_id = str(uuid.uuid4())
    object_key = f"uploads/{document_id}/document.pdf"
    uploaded_at = datetime.now(timezone.utc).isoformat()

    fields = {
        "Content-Type": PDF_CONTENT_TYPE,
        "x-amz-server-side-encryption": "AES256",
        "x-amz-meta-document-id": document_id,
        "x-amz-meta-original-filename": request["encoded_filename"],
        "x-amz-meta-uploaded-at": uploaded_at,
        "x-amz-meta-session-id": request["session_id"],
    }
    conditions: list[Any] = [
        {"Content-Type": PDF_CONTENT_TYPE},
        {"x-amz-server-side-encryption": "AES256"},
        {"x-amz-meta-document-id": document_id},
        {"x-amz-meta-original-filename": request["encoded_filename"]},
        {"x-amz-meta-uploaded-at": uploaded_at},
        {"x-amz-meta-session-id": request["session_id"]},
        ["content-length-range", 1, max_size_bytes],
    ]

    presigned_post = _get_s3_client().generate_presigned_post(
        Bucket=bucket_name,
        Key=object_key,
        Fields=fields,
        Conditions=conditions,
        ExpiresIn=expiration_seconds,
    )

    return {
        "documentId": document_id,
        "objectKey": object_key,
        "expiresIn": expiration_seconds,
        "upload": {
            "method": "POST",
            "url": presigned_post["url"],
            "fields": presigned_post["fields"],
        },
        "requirements": {
            "contentType": PDF_CONTENT_TYPE,
            "maxSizeBytes": max_size_bytes,
        },
    }


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Validate an upload request and return a short-lived S3 form."""
    request_id = getattr(context, "aws_request_id", "local")
    try:
        bucket_name = os.environ["DOCUMENTS_BUCKET_NAME"]
        max_size_bytes = int(
            os.environ.get("MAX_UPLOAD_SIZE_BYTES", str(DEFAULT_MAX_UPLOAD_SIZE_BYTES))
        )
        expiration_seconds = int(
            os.environ.get("UPLOAD_URL_EXPIRATION_SECONDS", str(DEFAULT_EXPIRATION_SECONDS))
        )
        payload = _parse_body(event)
        request = _validate_request(payload, max_size_bytes)
        response = _create_upload(
            request,
            bucket_name=bucket_name,
            max_size_bytes=max_size_bytes,
            expiration_seconds=expiration_seconds,
        )
        _log(
            "upload_url_created",
            request_id=request_id,
            document_id=response["documentId"],
            file_size=request["file_size"],
        )
        return _json_response(200, response)
    except RequestValidationError as error:
        _log(
            "upload_request_rejected",
            request_id=request_id,
            field=error.field,
        )
        return _json_response(
            400,
            {
                "error": {
                    "code": "VALIDATION_ERROR",
                    "field": error.field,
                    "message": error.message,
                }
            },
        )
    except (KeyError, TypeError, ValueError) as error:
        _log("upload_configuration_error", request_id=request_id, error_type=type(error).__name__)
        return _json_response(
            500,
            {
                "error": {
                    "code": "CONFIGURATION_ERROR",
                    "message": "The upload service is not configured correctly.",
                }
            },
        )
    except Exception as error:
        _log("presigned_post_failed", request_id=request_id, error_type=type(error).__name__)
        return _json_response(
            502,
            {
                "error": {
                    "code": "STORAGE_ERROR",
                    "message": "Could not create upload instructions.",
                }
            },
        )
