"""Generate validated Bedrock embeddings for page-aware document chunks."""

from __future__ import annotations

import json
import logging
import math
import os
import re
from datetime import UTC, datetime
from typing import Any

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)

DEFAULT_MODEL_ID = "amazon.titan-embed-text-v2:0"
DEFAULT_EMBEDDING_DIMENSIONS = 1_024
DEFAULT_MAX_EMBEDDING_CHUNKS = 500
DEFAULT_MAX_CHUNKS_FILE_SIZE_BYTES = 50 * 1024 * 1024
MAX_CHUNK_TEXT_CHARACTERS = 10_000
MAX_STATUS_FILE_SIZE_BYTES = 64 * 1024
CHUNKS_KEY_PATTERN = re.compile(
    r"^processing/([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})/chunks\.json$"
)

_s3_client: Any | None = None
_bedrock_client: Any | None = None


class EventIgnored(ValueError):
    """The event is outside this function's processing boundary."""


class EmbeddingInputRejected(ValueError):
    """The chunk artifact is permanently unsuitable for embedding."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _get_s3_client() -> Any:
    global _s3_client
    if _s3_client is None:
        import boto3

        _s3_client = boto3.client("s3")
    return _s3_client


def _get_bedrock_client() -> Any:
    global _bedrock_client
    if _bedrock_client is None:
        import boto3

        _bedrock_client = boto3.client("bedrock-runtime")
    return _bedrock_client


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
    etag = object_detail.get("etag")

    if bucket != expected_bucket:
        raise EventIgnored("The event references an unexpected bucket.")
    if not isinstance(key, str):
        raise EventIgnored("The event does not contain an object key.")

    match = CHUNKS_KEY_PATTERN.fullmatch(key)
    if match is None:
        raise EventIgnored("The object key is not a document chunk artifact.")
    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        raise EventIgnored("The event does not contain a valid object size.")

    return {
        "bucket": bucket,
        "key": key,
        "size": size,
        "etag": etag,
        "document_id": match.group(1),
    }


def _read_json_object(
    s3_client: Any,
    *,
    bucket: str,
    key: str,
    max_size_bytes: int,
) -> dict[str, Any]:
    response = s3_client.get_object(Bucket=bucket, Key=key)
    content_length = response.get("ContentLength")
    if not isinstance(content_length, int) or content_length < 1:
        raise EmbeddingInputRejected("EMPTY_CHUNKS_FILE", "The chunk artifact is empty.")
    if content_length > max_size_bytes:
        raise EmbeddingInputRejected(
            "CHUNKS_FILE_TOO_LARGE",
            f"The chunk artifact exceeds the {max_size_bytes}-byte limit.",
        )

    body = response["Body"].read(max_size_bytes + 1)
    if len(body) != content_length or len(body) > max_size_bytes:
        raise EmbeddingInputRejected(
            "CHUNKS_SIZE_MISMATCH",
            "The downloaded chunk artifact size does not match its metadata.",
        )
    try:
        parsed = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EmbeddingInputRejected(
            "INVALID_CHUNKS_JSON", "The chunk artifact is not valid JSON."
        ) from error
    if not isinstance(parsed, dict):
        raise EmbeddingInputRejected(
            "INVALID_CHUNKS_SCHEMA", "The chunk artifact must be a JSON object."
        )
    return parsed


def _validate_chunks(
    artifact: dict[str, Any],
    *,
    document_id: str,
    max_chunks: int,
) -> list[dict[str, Any]]:
    if (
        artifact.get("schemaVersion") != 1
        or artifact.get("documentId") != document_id
        or artifact.get("status") != "CHUNKED"
    ):
        raise EmbeddingInputRejected(
            "INVALID_CHUNKS_SCHEMA",
            "The chunk artifact identity or schema is invalid.",
        )

    chunks = artifact.get("chunks")
    if not isinstance(chunks, list) or not chunks:
        raise EmbeddingInputRejected(
            "NO_CHUNKS", "The chunk artifact contains no text chunks."
        )
    if len(chunks) > max_chunks:
        raise EmbeddingInputRejected(
            "TOO_MANY_EMBEDDING_CHUNKS",
            f"The document exceeds the {max_chunks}-chunk embedding limit.",
        )

    for index, chunk in enumerate(chunks):
        expected_id = f"{document_id}#chunk-{index + 1:05d}"
        if not isinstance(chunk, dict) or chunk.get("chunkId") != expected_id:
            raise EmbeddingInputRejected(
                "INVALID_CHUNK", f"Chunk {index} has an invalid identifier."
            )
        if chunk.get("chunkIndex") != index:
            raise EmbeddingInputRejected(
                "INVALID_CHUNK", f"Chunk {index} has an invalid index."
            )
        page_number = chunk.get("pageNumber")
        if isinstance(page_number, bool) or not isinstance(page_number, int) or page_number < 1:
            raise EmbeddingInputRejected(
                "INVALID_CHUNK", f"Chunk {index} has an invalid page number."
            )
        text = chunk.get("text")
        if not isinstance(text, str) or not text.strip():
            raise EmbeddingInputRejected(
                "INVALID_CHUNK", f"Chunk {index} has no text."
            )
        if len(text) > MAX_CHUNK_TEXT_CHARACTERS:
            raise EmbeddingInputRejected(
                "CHUNK_TEXT_TOO_LARGE",
                f"Chunk {index} exceeds the text-length limit.",
            )
        if chunk.get("characterCount") != len(text):
            raise EmbeddingInputRejected(
                "INVALID_CHUNK", f"Chunk {index} has an invalid character count."
            )
    return chunks


def _ensure_chunking_complete(
    s3_client: Any,
    *,
    bucket: str,
    document_id: str,
    chunks_key: str,
) -> None:
    """Prevent the downstream stage from racing the processor's final status write."""
    status_key = f"processing/{document_id}/status.json"
    try:
        response = s3_client.get_object(Bucket=bucket, Key=status_key)
        content_length = response.get("ContentLength")
        if (
            not isinstance(content_length, int)
            or content_length < 1
            or content_length > MAX_STATUS_FILE_SIZE_BYTES
        ):
            raise RuntimeError("Chunking completion status has an invalid size.")
        body = response["Body"].read(MAX_STATUS_FILE_SIZE_BYTES + 1)
        status = json.loads(body)
    except Exception as error:
        raise RuntimeError("Chunking completion status is not ready.") from error

    if (
        not isinstance(status, dict)
        or status.get("schemaVersion") != 1
        or status.get("documentId") != document_id
        or status.get("status") != "CHUNKED"
        or status.get("chunksKey") != chunks_key
    ):
        raise RuntimeError("Chunking completion status is not ready.")


def _embed_text(
    bedrock_client: Any,
    *,
    text: str,
    model_id: str,
    dimensions: int,
    normalize: bool,
) -> tuple[list[float], int | None]:
    response = bedrock_client.invoke_model(
        modelId=model_id,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(
            {"inputText": text, "dimensions": dimensions, "normalize": normalize},
            separators=(",", ":"),
        ).encode("utf-8"),
    )
    try:
        payload = json.loads(response["body"].read())
        vector = payload["embedding"]
        token_count = payload.get("inputTextTokenCount")
    except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("Bedrock returned an invalid embedding response.") from error

    if (
        not isinstance(vector, list)
        or len(vector) != dimensions
        or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            for value in vector
        )
    ):
        raise RuntimeError("Bedrock returned an invalid embedding vector.")
    if token_count is not None and (
        isinstance(token_count, bool) or not isinstance(token_count, int) or token_count < 0
    ):
        raise RuntimeError("Bedrock returned an invalid token count.")
    return [float(value) for value in vector], token_count


def _put_json(s3_client: Any, *, bucket: str, key: str, body: dict[str, Any]) -> None:
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        ContentType="application/json",
        CacheControl="no-store",
        ServerSideEncryption="AES256",
    )


def _failure_status(source: dict[str, Any], error: EmbeddingInputRejected) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "documentId": source["document_id"],
        "status": "FAILED",
        "stage": "EMBEDDING",
        "error": {"code": error.code, "message": error.message},
        "chunksKey": source["key"],
        "updatedAt": _utc_now(),
    }


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Embed one chunks.json artifact delivered through Amazon EventBridge."""
    request_id = getattr(context, "aws_request_id", "local")
    bucket_name = os.environ["DOCUMENTS_BUCKET_NAME"]
    model_id = os.environ.get("EMBEDDING_MODEL_ID", DEFAULT_MODEL_ID)
    dimensions = int(
        os.environ.get("EMBEDDING_DIMENSIONS", str(DEFAULT_EMBEDDING_DIMENSIONS))
    )
    normalize = os.environ.get("NORMALIZE_EMBEDDINGS", "true").lower() == "true"
    max_chunks = int(
        os.environ.get("MAX_EMBEDDING_CHUNKS", str(DEFAULT_MAX_EMBEDDING_CHUNKS))
    )
    max_file_size = int(
        os.environ.get(
            "MAX_CHUNKS_FILE_SIZE_BYTES", str(DEFAULT_MAX_CHUNKS_FILE_SIZE_BYTES)
        )
    )
    if dimensions < 1 or max_chunks < 1 or max_file_size < 1:
        raise ValueError("Embedding configuration values must be positive.")

    try:
        source = _parse_event(event, bucket_name)
    except EventIgnored as error:
        _log("embedding_event_ignored", request_id=request_id, reason=str(error))
        return {"status": "IGNORED", "reason": str(error)}

    status_key = f"processing/{source['document_id']}/status.json"
    try:
        _ensure_chunking_complete(
            _get_s3_client(),
            bucket=source["bucket"],
            document_id=source["document_id"],
            chunks_key=source["key"],
        )
        artifact = _read_json_object(
            _get_s3_client(),
            bucket=source["bucket"],
            key=source["key"],
            max_size_bytes=max_file_size,
        )
        chunks = _validate_chunks(
            artifact,
            document_id=source["document_id"],
            max_chunks=max_chunks,
        )

        embeddings = []
        for chunk in chunks:
            vector, token_count = _embed_text(
                _get_bedrock_client(),
                text=chunk["text"],
                model_id=model_id,
                dimensions=dimensions,
                normalize=normalize,
            )
            embeddings.append(
                {
                    "chunkId": chunk["chunkId"],
                    "chunkIndex": chunk["chunkIndex"],
                    "pageNumber": chunk["pageNumber"],
                    "inputTextTokenCount": token_count,
                    "embedding": vector,
                }
            )

        embeddings_key = f"processing/{source['document_id']}/embeddings.json"
        output = {
            "schemaVersion": 1,
            "documentId": source["document_id"],
            "status": "EMBEDDED",
            "sourceChunksKey": source["key"],
            "modelId": model_id,
            "dimensions": dimensions,
            "normalized": normalize,
            "chunkCount": len(embeddings),
            "embeddings": embeddings,
            "embeddedAt": _utc_now(),
        }
        _put_json(_get_s3_client(), bucket=source["bucket"], key=embeddings_key, body=output)

        status = {
            "schemaVersion": 1,
            "documentId": source["document_id"],
            "status": "EMBEDDED",
            "chunksKey": source["key"],
            "embeddingsKey": embeddings_key,
            "modelId": model_id,
            "dimensions": dimensions,
            "chunkCount": len(embeddings),
            "updatedAt": _utc_now(),
        }
        _put_json(_get_s3_client(), bucket=source["bucket"], key=status_key, body=status)
        _log(
            "document_embedded",
            request_id=request_id,
            document_id=source["document_id"],
            model_id=model_id,
            dimensions=dimensions,
            chunk_count=len(embeddings),
        )
        return status
    except EmbeddingInputRejected as error:
        status = _failure_status(source, error)
        _put_json(_get_s3_client(), bucket=source["bucket"], key=status_key, body=status)
        _log(
            "embedding_input_rejected",
            request_id=request_id,
            document_id=source["document_id"],
            error_code=error.code,
        )
        return status
    except Exception as error:
        _log(
            "embedding_generation_failed",
            request_id=request_id,
            document_id=source["document_id"],
            error_type=type(error).__name__,
        )
        raise
