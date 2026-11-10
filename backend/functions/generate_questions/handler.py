"""HTTP Lambda for summaries, key concepts, questions, and study guides."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from shared.rag import cited_source_numbers
from shared.retrieval import RetrievalValidationError, retrieve_chunks, validate_document_ids
from shared.study import generate_study_material, retrieval_query, validate_study_request

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)
MAX_REQUEST_BODY_BYTES = 8 * 1024
_bedrock_client: Any | None = None


def _client() -> Any:
    global _bedrock_client
    if _bedrock_client is None:
        import boto3
        _bedrock_client = boto3.client("bedrock-runtime")
    return _bedrock_client


def _response(status: int, body: dict[str, Any]) -> dict[str, Any]:
    return {"statusCode": status, "headers": {"Content-Type": "application/json", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}, "body": json.dumps(body, separators=(",", ":"))}


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    if event.get("isBase64Encoded"):
        raise RetrievalValidationError("body", "Base64 request bodies are not supported.")
    body = event.get("body", event)
    if isinstance(body, str):
        if len(body.encode("utf-8")) > MAX_REQUEST_BODY_BYTES:
            raise RetrievalValidationError("body", "Request body is too large.")
        if event.get("requestContext"):
            content_type = (event.get("headers") or {}).get("content-type", "")
            if content_type.split(";", 1)[0].strip().lower() != "application/json":
                raise RetrievalValidationError("contentType", "Content-Type must be application/json.")
        try:
            body = json.loads(body)
        except json.JSONDecodeError as error:
            raise RetrievalValidationError("body", "Request body must be valid JSON.") from error
    if not isinstance(body, dict):
        raise RetrievalValidationError("body", "Request body must be a JSON object.")
    return body


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    request_id = getattr(context, "aws_request_id", "local")
    try:
        raw = _payload(event)
        request = validate_study_request(raw)
        document_ids = validate_document_ids(raw.get("documentIds"))
        if not document_ids:
            raise RetrievalValidationError(
                "documentIds", "Select at least one indexed document for study tools."
            )
        chunks = retrieve_chunks(
            _client(), question=retrieval_query(request), model_id=os.environ["EMBEDDING_MODEL_ID"],
            dimensions=int(os.environ["EMBEDDING_DIMENSIONS"]), endpoint=os.environ["OPENSEARCH_COLLECTION_ENDPOINT"],
            region=os.environ.get("AWS_REGION", "us-east-1"), index_name=os.environ["OPENSEARCH_INDEX_NAME"],
            top_k=int(os.environ.get("STUDY_RETRIEVAL_TOP_K", "10")),
            min_score=float(os.environ.get("STUDY_RETRIEVAL_MIN_SCORE", "0.0")),
            document_ids=document_ids,
        )
        if not chunks:
            return _response(200, {"title": "No relevant material", "content": "I could not find sufficient information in the selected course materials.", "noAnswer": True, "sources": []})
        generated = generate_study_material(
            _client(), model_id=os.environ["GENERATION_MODEL_ID"], request=request, chunks=chunks,
            max_context_characters=int(os.environ.get("MAX_RAG_CONTEXT_CHARACTERS", "12000")),
            max_output_tokens=int(os.environ.get("MAX_STUDY_TOKENS", "1400")),
        )
        sources = [{"sourceNumber": i, "documentId": chunk["documentId"], "filename": chunk.get("filename", "document.pdf"), "chunkId": chunk["chunkId"], "pageNumber": chunk["pageNumber"], "score": chunk["score"]} for i, chunk in enumerate(chunks, 1)]
        cited_numbers = cited_source_numbers(generated["content"], len(sources))
        if not cited_numbers:
            LOGGER.warning(json.dumps({"event": "study_output_missing_citations", "request_id": request_id, "mode": request["mode"]}, separators=(",", ":")))
            return _response(502, {"error": {"code": "UNGROUNDED_MODEL_RESPONSE", "message": "The study material could not be tied to a source. Please try again."}})
        cited_sources = [source for source in sources if source["sourceNumber"] in cited_numbers]
        LOGGER.info(json.dumps({"event": "study_material_generated", "request_id": request_id, "mode": request["mode"], "source_count": len(sources)}, separators=(",", ":")))
        return _response(200, {"title": generated["title"], "content": generated["content"], "noAnswer": False, "sources": cited_sources})
    except RetrievalValidationError as error:
        return _response(400, {"error": {"code": "VALIDATION_ERROR", "field": error.field, "message": error.message}})
    except (KeyError, TypeError, ValueError):
        return _response(500, {"error": {"code": "CONFIGURATION_ERROR", "message": "The study service is not configured correctly."}})
    except Exception as error:
        LOGGER.exception(json.dumps({"event": "study_service_error", "request_id": request_id, "error_type": type(error).__name__}))
        return _response(502, {"error": {"code": "UPSTREAM_SERVICE_ERROR", "message": "The AI service is temporarily unavailable."}})
