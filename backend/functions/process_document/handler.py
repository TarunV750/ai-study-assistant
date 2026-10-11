"""Validate uploaded PDFs and create page-aware text and chunks in private S3."""

from __future__ import annotations

import io
import json
import logging
import os
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import unquote

from shared.chunking import ChunkingConfig, ChunkLimitExceeded, chunk_pages

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)

PDF_CONTENT_TYPE = "application/pdf"
DEFAULT_MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024
DEFAULT_MAX_PDF_PAGES = 200
DEFAULT_MAX_EXTRACTED_CHARACTERS = 2_000_000
DEFAULT_CHUNK_SIZE_CHARACTERS = 1_200
DEFAULT_CHUNK_OVERLAP_CHARACTERS = 200
DEFAULT_MAX_CHUNKS_PER_DOCUMENT = 5_000
UPLOAD_KEY_PATTERN = re.compile(
    r"^uploads/([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})/document\.pdf$"
)

_s3_client: Any | None = None


class EventIgnored(ValueError):
    """The event is outside this function's processing boundary."""


class DocumentRejected(ValueError):
    """An uploaded object is permanently unsuitable for text extraction."""

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

    match = UPLOAD_KEY_PATTERN.fullmatch(key)
    if match is None:
        raise EventIgnored("The object key is outside the PDF upload prefix.")
    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        raise EventIgnored("The event does not contain a valid object size.")

    return {
        "bucket": bucket,
        "key": key,
        "size": size,
        "etag": etag,
        "document_id": match.group(1),
    }


def _normalize_page_text(text: str) -> str:
    """Perform lossless cleanup while keeping paragraph and page boundaries."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    lines = [line.rstrip() for line in text.split("\n")]
    normalized: list[str] = []
    blank = False
    for line in lines:
        if line.strip():
            normalized.append(line)
            blank = False
        elif not blank:
            normalized.append("")
            blank = True
    return "\n".join(normalized).strip()


def _extract_pages(
    pdf_bytes: bytes,
    *,
    max_pages: int,
    max_characters: int,
) -> tuple[list[dict[str, Any]], int]:
    if b"%PDF-" not in pdf_bytes[:1024]:
        raise DocumentRejected("INVALID_PDF_SIGNATURE", "The uploaded object is not a PDF file.")

    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(pdf_bytes), strict=True)
        if reader.is_encrypted:
            raise DocumentRejected(
                "ENCRYPTED_PDF", "Password-protected PDF files are not supported."
            )
        page_count = len(reader.pages)
        if page_count < 1:
            raise DocumentRejected("EMPTY_PDF", "The PDF contains no pages.")
        if page_count > max_pages:
            raise DocumentRejected(
                "TOO_MANY_PAGES", f"The PDF exceeds the {max_pages}-page processing limit."
            )

        pages: list[dict[str, Any]] = []
        character_count = 0
        for page_number, page in enumerate(reader.pages, start=1):
            text = _normalize_page_text(page.extract_text() or "")
            character_count += len(text)
            if character_count > max_characters:
                raise DocumentRejected(
                    "TEXT_LIMIT_EXCEEDED",
                    f"Extracted text exceeds the {max_characters}-character processing limit.",
                )
            pages.append({"pageNumber": page_number, "text": text})
    except DocumentRejected:
        raise
    except Exception as error:
        raise DocumentRejected("PDF_EXTRACTION_FAILED", "The PDF could not be parsed.") from error

    if character_count == 0:
        raise DocumentRejected(
            "NO_EXTRACTABLE_TEXT",
            "The PDF contains no extractable text; scanned image-only PDFs are not supported yet.",
        )
    return pages, character_count


def _put_json(s3_client: Any, *, bucket: str, key: str, body: dict[str, Any]) -> None:
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        ContentType="application/json",
        CacheControl="no-store",
        ServerSideEncryption="AES256",
    )


def _failure_status(source: dict[str, Any], error: DocumentRejected) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "documentId": source["document_id"],
        "status": "FAILED",
        "error": {"code": error.code, "message": error.message},
        "sourceKey": source["key"],
        "updatedAt": _utc_now(),
    }


def _process_document(
    source: dict[str, Any],
    *,
    s3_client: Any,
    max_size_bytes: int,
    max_pages: int,
    max_characters: int,
    chunking_config: ChunkingConfig,
) -> dict[str, Any]:
    bucket = source["bucket"]
    key = source["key"]
    document_id = source["document_id"]
    status_key = f"processing/{document_id}/status.json"

    try:
        head = s3_client.head_object(Bucket=bucket, Key=key)
        content_length = head.get("ContentLength")
        if not isinstance(content_length, int) or content_length < 1:
            raise DocumentRejected("EMPTY_FILE", "The uploaded PDF is empty.")
        if content_length > max_size_bytes:
            raise DocumentRejected(
                "FILE_TOO_LARGE", f"The PDF exceeds the {max_size_bytes}-byte processing limit."
            )
        if head.get("ContentType") != PDF_CONTENT_TYPE:
            raise DocumentRejected("INVALID_CONTENT_TYPE", "The object is not application/pdf.")

        metadata = head.get("Metadata") or {}
        if metadata.get("document-id") != document_id:
            raise DocumentRejected(
                "METADATA_MISMATCH", "The document ID metadata does not match the object key."
            )

        response = s3_client.get_object(Bucket=bucket, Key=key)
        pdf_bytes = response["Body"].read(max_size_bytes + 1)
        if len(pdf_bytes) != content_length or len(pdf_bytes) > max_size_bytes:
            raise DocumentRejected(
                "SIZE_MISMATCH", "The downloaded PDF size does not match its object metadata."
            )

        pages, character_count = _extract_pages(
            pdf_bytes,
            max_pages=max_pages,
            max_characters=max_characters,
        )
        try:
            chunks = chunk_pages(
                pages,
                document_id=document_id,
                config=chunking_config,
            )
        except ChunkLimitExceeded as error:
            raise DocumentRejected("TOO_MANY_CHUNKS", str(error)) from error

        extracted_key = f"processing/{document_id}/extracted.json"
        extracted = {
            "schemaVersion": 1,
            "documentId": document_id,
            "status": "EXTRACTED",
            "source": {
                "bucket": bucket,
                "key": key,
                "etag": source.get("etag"),
                "sizeBytes": content_length,
                "contentType": head.get("ContentType"),
                "originalFilename": unquote(metadata.get("original-filename", "document.pdf")),
                "uploadedAt": metadata.get("uploaded-at"),
                "sessionId": metadata.get("session-id"),
            },
            "pageCount": len(pages),
            "characterCount": character_count,
            "pages": pages,
            "extractedAt": _utc_now(),
        }
        _put_json(s3_client, bucket=bucket, key=extracted_key, body=extracted)

        chunks_key = f"processing/{document_id}/chunks.json"
        chunked = {
            "schemaVersion": 1,
            "documentId": document_id,
            "status": "CHUNKED",
            "sourceExtractedKey": extracted_key,
            "strategy": {
                "unit": "characters",
                "maxCharacters": chunking_config.max_characters,
                "overlapCharacters": chunking_config.overlap_characters,
                "pageBoundaryBehavior": "preserve",
            },
            "chunkCount": len(chunks),
            "chunks": chunks,
            "chunkedAt": _utc_now(),
        }
        _put_json(s3_client, bucket=bucket, key=chunks_key, body=chunked)

        status = {
            "schemaVersion": 1,
            "documentId": document_id,
            "status": "CHUNKED",
            "sourceKey": key,
            "extractedKey": extracted_key,
            "chunksKey": chunks_key,
            "pageCount": len(pages),
            "characterCount": character_count,
            "chunkCount": len(chunks),
            "updatedAt": _utc_now(),
        }
        _put_json(s3_client, bucket=bucket, key=status_key, body=status)
        return status
    except DocumentRejected as error:
        status = _failure_status(source, error)
        _put_json(s3_client, bucket=bucket, key=status_key, body=status)
        raise


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Process one S3 Object Created event delivered by Amazon EventBridge."""
    request_id = getattr(context, "aws_request_id", "local")
    bucket_name = os.environ["DOCUMENTS_BUCKET_NAME"]
    max_size_bytes = int(
        os.environ.get("MAX_UPLOAD_SIZE_BYTES", str(DEFAULT_MAX_UPLOAD_SIZE_BYTES))
    )
    max_pages = int(os.environ.get("MAX_PDF_PAGES", str(DEFAULT_MAX_PDF_PAGES)))
    max_characters = int(
        os.environ.get(
            "MAX_EXTRACTED_CHARACTERS", str(DEFAULT_MAX_EXTRACTED_CHARACTERS)
        )
    )
    chunking_config = ChunkingConfig(
        max_characters=int(
            os.environ.get(
                "CHUNK_SIZE_CHARACTERS", str(DEFAULT_CHUNK_SIZE_CHARACTERS)
            )
        ),
        overlap_characters=int(
            os.environ.get(
                "CHUNK_OVERLAP_CHARACTERS",
                str(DEFAULT_CHUNK_OVERLAP_CHARACTERS),
            )
        ),
        max_chunks=int(
            os.environ.get(
                "MAX_CHUNKS_PER_DOCUMENT", str(DEFAULT_MAX_CHUNKS_PER_DOCUMENT)
            )
        ),
    )
    chunking_config.validate()

    try:
        source = _parse_event(event, bucket_name)
    except EventIgnored as error:
        _log("document_event_ignored", request_id=request_id, reason=str(error))
        return {"status": "IGNORED", "reason": str(error)}

    try:
        status = _process_document(
            source,
            s3_client=_get_s3_client(),
            max_size_bytes=max_size_bytes,
            max_pages=max_pages,
            max_characters=max_characters,
            chunking_config=chunking_config,
        )
        _log(
            "document_chunked",
            request_id=request_id,
            document_id=source["document_id"],
            page_count=status["pageCount"],
            character_count=status["characterCount"],
            chunk_count=status["chunkCount"],
        )
        return status
    except DocumentRejected as error:
        _log(
            "document_rejected",
            request_id=request_id,
            document_id=source["document_id"],
            error_code=error.code,
        )
        return _failure_status(source, error)
    except Exception as error:
        _log(
            "document_processing_failed",
            request_id=request_id,
            document_id=source["document_id"],
            error_type=type(error).__name__,
        )
        raise
