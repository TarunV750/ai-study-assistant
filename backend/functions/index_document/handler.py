"""Index validated chunks and Bedrock embeddings in OpenSearch Serverless."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)

DEFAULT_MAX_ARTIFACT_SIZE_BYTES = 50 * 1024 * 1024
DEFAULT_MAX_INDEX_CHUNKS = 500
DEFAULT_BULK_BATCH_SIZE = 50
MAX_CHUNK_TEXT_CHARACTERS = 10_000
MAX_STATUS_FILE_SIZE_BYTES = 64 * 1024
EMBEDDINGS_KEY_PATTERN = re.compile(
    r"^processing/([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12})/embeddings\.json$"
)

_s3_client: Any | None = None


class EventIgnored(ValueError):
    """The event is outside this function's processing boundary."""


class IndexInputRejected(ValueError):
    """The artifacts are permanently unsuitable for indexing."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class OpenSearchRequestError(RuntimeError):
    """An OpenSearch request returned an unsuccessful HTTP status."""

    def __init__(self, status_code: int, response_body: str) -> None:
        super().__init__(f"OpenSearch returned HTTP {status_code}: {response_body}")
        self.status_code = status_code
        self.response_body = response_body


def _get_s3_client() -> Any:
    global _s3_client
    if _s3_client is None:
        import boto3

        _s3_client = boto3.client("s3")
    return _s3_client


def _log(event_name: str, **details: Any) -> None:
    LOGGER.info(json.dumps({"event": event_name, **details}, separators=(",", ":")))


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_event(event: dict[str, Any], expected_bucket: str) -> dict[str, Any]:
    if event.get("source") != "aws.s3" or event.get("detail-type") != "Object Created":
        raise EventIgnored("Only Amazon S3 Object Created events are supported.")

    detail = event.get("detail")
    if not isinstance(detail, dict):
        raise EventIgnored("Event detail is missing.")

    bucket = detail.get("bucket", {}).get("name")
    object_detail = detail.get("object", {})
    key = object_detail.get("key")
    size = object_detail.get("size")
    if bucket != expected_bucket:
        raise EventIgnored("The event references an unexpected bucket.")
    if not isinstance(key, str):
        raise EventIgnored("The event does not contain an object key.")

    match = EMBEDDINGS_KEY_PATTERN.fullmatch(key)
    if match is None:
        raise EventIgnored("The object key is not a document embedding artifact.")
    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        raise EventIgnored("The event does not contain a valid object size.")
    return {
        "bucket": bucket,
        "key": key,
        "size": size,
        "document_id": match.group(1),
    }


def _read_json_object(
    s3_client: Any, *, bucket: str, key: str, max_size_bytes: int
) -> dict[str, Any]:
    response = s3_client.get_object(Bucket=bucket, Key=key)
    content_length = response.get("ContentLength")
    if not isinstance(content_length, int) or content_length < 1:
        raise IndexInputRejected("EMPTY_ARTIFACT", f"{key} is empty.")
    if content_length > max_size_bytes:
        raise IndexInputRejected(
            "ARTIFACT_TOO_LARGE", f"{key} exceeds the {max_size_bytes}-byte limit."
        )

    body = response["Body"].read(max_size_bytes + 1)
    if len(body) != content_length or len(body) > max_size_bytes:
        raise IndexInputRejected(
            "ARTIFACT_SIZE_MISMATCH", f"The downloaded size for {key} is invalid."
        )
    try:
        parsed = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise IndexInputRejected("INVALID_ARTIFACT_JSON", f"{key} is not valid JSON.") from error
    if not isinstance(parsed, dict):
        raise IndexInputRejected("INVALID_ARTIFACT_SCHEMA", f"{key} must be a JSON object.")
    return parsed


def _ensure_embedding_complete(
    s3_client: Any,
    *,
    bucket: str,
    document_id: str,
    embeddings_key: str,
    chunks_key: str,
) -> None:
    """Prevent the event from racing the embedding Lambda's final status write."""
    status_key = f"processing/{document_id}/status.json"
    try:
        response = s3_client.get_object(Bucket=bucket, Key=status_key)
        content_length = response.get("ContentLength")
        if (
            not isinstance(content_length, int)
            or content_length < 1
            or content_length > MAX_STATUS_FILE_SIZE_BYTES
        ):
            raise RuntimeError("Embedding completion status has an invalid size.")
        body = response["Body"].read(MAX_STATUS_FILE_SIZE_BYTES + 1)
        status = json.loads(body)
    except Exception as error:
        raise RuntimeError("Embedding completion status is not ready.") from error

    if (
        not isinstance(status, dict)
        or status.get("schemaVersion") != 1
        or status.get("documentId") != document_id
        or status.get("status") not in {"EMBEDDED", "INDEXED"}
        or status.get("embeddingsKey") != embeddings_key
        or status.get("chunksKey") != chunks_key
    ):
        raise RuntimeError("Embedding completion status is not ready.")


def _validated_documents(
    chunks_artifact: dict[str, Any],
    embeddings_artifact: dict[str, Any],
    *,
    document_id: str,
    expected_dimensions: int,
    max_chunks: int,
) -> list[dict[str, Any]]:
    chunks = chunks_artifact.get("chunks")
    embeddings = embeddings_artifact.get("embeddings")
    source = chunks_artifact.get("source", {})
    filename = source.get("originalFilename", "document.pdf") if isinstance(source, dict) else "document.pdf"
    if (
        chunks_artifact.get("schemaVersion") != 1
        or chunks_artifact.get("documentId") != document_id
        or chunks_artifact.get("status") != "CHUNKED"
        or embeddings_artifact.get("schemaVersion") != 1
        or embeddings_artifact.get("documentId") != document_id
        or embeddings_artifact.get("status") != "EMBEDDED"
        or embeddings_artifact.get("dimensions") != expected_dimensions
        or not isinstance(chunks, list)
        or not isinstance(embeddings, list)
        or not chunks
        or len(chunks) != len(embeddings)
        or chunks_artifact.get("chunkCount") != len(chunks)
        or embeddings_artifact.get("chunkCount") != len(embeddings)
        or not isinstance(filename, str)
        or not filename.strip()
        or len(filename) > 255
    ):
        raise IndexInputRejected(
            "INVALID_INDEX_ARTIFACTS", "The chunk and embedding artifact contracts do not match."
        )
    if len(chunks) > max_chunks:
        raise IndexInputRejected(
            "TOO_MANY_INDEX_CHUNKS", f"The document exceeds the {max_chunks}-chunk index limit."
        )

    documents: list[dict[str, Any]] = []
    for index, (chunk, embedded) in enumerate(zip(chunks, embeddings, strict=True)):
        expected_id = f"{document_id}#chunk-{index + 1:05d}"
        if not isinstance(chunk, dict) or not isinstance(embedded, dict):
            raise IndexInputRejected("INVALID_INDEX_CHUNK", f"Chunk {index} is invalid.")
        if (
            chunk.get("chunkId") != expected_id
            or embedded.get("chunkId") != expected_id
            or chunk.get("chunkIndex") != index
            or embedded.get("chunkIndex") != index
            or embedded.get("pageNumber") != chunk.get("pageNumber")
        ):
            raise IndexInputRejected(
                "MISMATCHED_INDEX_CHUNK", f"Chunk {index} does not match its embedding."
            )

        text = chunk.get("text")
        page_number = chunk.get("pageNumber")
        start = chunk.get("startCharacter")
        end = chunk.get("endCharacter")
        vector = embedded.get("embedding")
        integer_fields = (page_number, start, end, chunk.get("pageChunkIndex"))
        if (
            not isinstance(text, str)
            or not text.strip()
            or len(text) > MAX_CHUNK_TEXT_CHARACTERS
            or chunk.get("characterCount") != len(text)
            or any(
                isinstance(value, bool) or not isinstance(value, int)
                for value in integer_fields
            )
            or page_number < 1
            or start < 0
            or end <= start
            or end - start != len(text)
            or not isinstance(vector, list)
            or len(vector) != expected_dimensions
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                for value in vector
            )
        ):
            raise IndexInputRejected("INVALID_INDEX_CHUNK", f"Chunk {index} is invalid.")

        documents.append(
            {
                "document_id": document_id,
                "filename": filename.strip(),
                "chunk_id": expected_id,
                "chunk_index": index,
                "page_number": page_number,
                "page_chunk_index": chunk["pageChunkIndex"],
                "start_character": start,
                "end_character": end,
                "character_count": len(text),
                "text": text,
                "embedding_model": embeddings_artifact.get("modelId"),
                "chunk_vector": [float(value) for value in vector],
            }
        )
    return documents


def _signed_opensearch_request(
    *,
    endpoint: str,
    region: str,
    method: str,
    path: str,
    body: bytes,
    content_type: str = "application/json",
) -> dict[str, Any]:
    """Send one SigV4-signed OpenSearch Serverless request with runtime libraries."""
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest
    from botocore.session import Session

    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.netloc or parsed.path not in ("", "/"):
        raise ValueError("OPENSEARCH_COLLECTION_ENDPOINT must be an HTTPS origin.")
    url = f"{endpoint.rstrip('/')}/{path.lstrip('/')}"
    payload_hash = hashlib.sha256(body).hexdigest()
    headers = {
        "Content-Type": content_type,
        "x-amz-content-sha256": payload_hash,
    }
    credentials = Session().get_credentials()
    if credentials is None:
        raise RuntimeError("AWS credentials are unavailable for OpenSearch signing.")
    aws_request = AWSRequest(method=method, url=url, data=body, headers=headers)
    SigV4Auth(credentials.get_frozen_credentials(), "aoss", region).add_auth(aws_request)
    request = urllib.request.Request(
        url=url,
        data=body,
        headers=dict(aws_request.headers.items()),
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read()
    except urllib.error.HTTPError as error:
        response_body = error.read().decode("utf-8", errors="replace")[:1_000]
        raise OpenSearchRequestError(error.code, response_body) from error
    if not payload:
        return {}
    try:
        parsed_body = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("OpenSearch returned a non-JSON response.") from error
    if not isinstance(parsed_body, dict):
        raise RuntimeError("OpenSearch returned an invalid response.")
    return parsed_body


def _ensure_index(
    *, endpoint: str, region: str, index_name: str, dimensions: int
) -> None:
    """Create the vector index once, tolerating concurrent first-document events."""
    try:
        _signed_opensearch_request(
            endpoint=endpoint,
            region=region,
            method="HEAD",
            path=index_name,
            body=b"",
        )
        return
    except OpenSearchRequestError as error:
        if error.status_code != 404:
            raise

    definition = {
        "settings": {"index": {"knn": True}},
        "mappings": {
            "properties": {
                "document_id": {"type": "keyword"},
                "filename": {"type": "keyword", "ignore_above": 255},
                "chunk_id": {"type": "keyword"},
                "chunk_index": {"type": "integer"},
                "page_number": {"type": "integer"},
                "page_chunk_index": {"type": "integer"},
                "start_character": {"type": "integer"},
                "end_character": {"type": "integer"},
                "character_count": {"type": "integer"},
                "text": {"type": "text"},
                "embedding_model": {"type": "keyword"},
                "chunk_vector": {
                    "type": "knn_vector",
                    "dimension": dimensions,
                    "space_type": "cosinesimil",
                },
            }
        },
    }
    try:
        _signed_opensearch_request(
            endpoint=endpoint,
            region=region,
            method="PUT",
            path=index_name,
            body=json.dumps(definition, separators=(",", ":")).encode("utf-8"),
        )
    except OpenSearchRequestError as error:
        already_exists = "resource_already_exists_exception" in error.response_body
        if error.status_code != 400 or not already_exists:
            raise


def _bulk_index(
    documents: list[dict[str, Any]],
    *,
    endpoint: str,
    region: str,
    index_name: str,
    batch_size: int,
) -> None:
    for start in range(0, len(documents), batch_size):
        lines: list[str] = []
        batch = documents[start : start + batch_size]
        for document in batch:
            lines.append(
                json.dumps(
                    {"index": {"_index": index_name, "_id": document["chunk_id"]}},
                    separators=(",", ":"),
                )
            )
            lines.append(json.dumps(document, ensure_ascii=False, separators=(",", ":")))
        body = ("\n".join(lines) + "\n").encode("utf-8")
        response = _signed_opensearch_request(
            endpoint=endpoint,
            region=region,
            method="POST",
            path="_bulk",
            body=body,
            content_type="application/x-ndjson",
        )
        items = response.get("items")
        if (
            response.get("errors") is not False
            or not isinstance(items, list)
            or len(items) != len(batch)
        ):
            raise RuntimeError("OpenSearch bulk indexing reported one or more failures.")


def _put_json(s3_client: Any, *, bucket: str, key: str, body: dict[str, Any]) -> None:
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        ContentType="application/json",
        CacheControl="no-store",
        ServerSideEncryption="AES256",
    )


def _failure_status(source: dict[str, Any], error: IndexInputRejected) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "documentId": source["document_id"],
        "status": "FAILED",
        "stage": "INDEXING",
        "error": {"code": error.code, "message": error.message},
        "embeddingsKey": source["key"],
        "updatedAt": _utc_now(),
    }


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Index one embeddings.json artifact delivered through EventBridge."""
    request_id = getattr(context, "aws_request_id", "local")
    bucket_name = os.environ["DOCUMENTS_BUCKET_NAME"]
    endpoint = os.environ["OPENSEARCH_COLLECTION_ENDPOINT"]
    index_name = os.environ["OPENSEARCH_INDEX_NAME"]
    region = os.environ.get("AWS_REGION", "us-east-1")
    dimensions = int(os.environ["EMBEDDING_DIMENSIONS"])
    max_chunks = int(os.environ.get("MAX_INDEX_CHUNKS", str(DEFAULT_MAX_INDEX_CHUNKS)))
    max_size = int(
        os.environ.get("MAX_INDEX_ARTIFACT_SIZE_BYTES", str(DEFAULT_MAX_ARTIFACT_SIZE_BYTES))
    )
    batch_size = int(os.environ.get("INDEX_BULK_BATCH_SIZE", str(DEFAULT_BULK_BATCH_SIZE)))
    if dimensions < 1 or max_chunks < 1 or max_size < 1 or batch_size < 1:
        raise ValueError("Indexing configuration values must be positive.")

    try:
        source = _parse_event(event, bucket_name)
    except EventIgnored as error:
        _log("index_event_ignored", request_id=request_id, reason=str(error))
        return {"status": "IGNORED", "reason": str(error)}

    status_key = f"processing/{source['document_id']}/status.json"
    chunks_key = f"processing/{source['document_id']}/chunks.json"
    try:
        _ensure_embedding_complete(
            _get_s3_client(),
            bucket=source["bucket"],
            document_id=source["document_id"],
            embeddings_key=source["key"],
            chunks_key=chunks_key,
        )
        chunks_artifact = _read_json_object(
            _get_s3_client(), bucket=source["bucket"], key=chunks_key, max_size_bytes=max_size
        )
        embeddings_artifact = _read_json_object(
            _get_s3_client(),
            bucket=source["bucket"],
            key=source["key"],
            max_size_bytes=max_size,
        )
        documents = _validated_documents(
            chunks_artifact,
            embeddings_artifact,
            document_id=source["document_id"],
            expected_dimensions=dimensions,
            max_chunks=max_chunks,
        )
        _ensure_index(
            endpoint=endpoint,
            region=region,
            index_name=index_name,
            dimensions=dimensions,
        )
        _bulk_index(
            documents,
            endpoint=endpoint,
            region=region,
            index_name=index_name,
            batch_size=batch_size,
        )

        status = {
            "schemaVersion": 1,
            "documentId": source["document_id"],
            "status": "INDEXED",
            "chunksKey": chunks_key,
            "embeddingsKey": source["key"],
            "indexName": index_name,
            "chunkCount": len(documents),
            "updatedAt": _utc_now(),
        }
        _put_json(_get_s3_client(), bucket=source["bucket"], key=status_key, body=status)
        _log(
            "document_indexed",
            request_id=request_id,
            document_id=source["document_id"],
            index_name=index_name,
            chunk_count=len(documents),
        )
        return status
    except IndexInputRejected as error:
        status = _failure_status(source, error)
        _put_json(_get_s3_client(), bucket=source["bucket"], key=status_key, body=status)
        _log(
            "index_input_rejected",
            request_id=request_id,
            document_id=source["document_id"],
            error_code=error.code,
        )
        return status
    except Exception as error:
        _log(
            "document_indexing_failed",
            request_id=request_id,
            document_id=source["document_id"],
            error_type=type(error).__name__,
        )
        raise
