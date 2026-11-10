"""HTTP Lambda for grounded retrieval-augmented question answering."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from shared.rag import NO_ANSWER_MESSAGE, generate_grounded_answer
from shared.retrieval import (
    DEFAULT_MIN_SCORE,
    DEFAULT_TOP_K,
    RetrievalValidationError,
    retrieve_chunks,
    validate_document_ids,
    validate_question,
)

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)

_bedrock_client: Any | None = None


def _get_bedrock_client() -> Any:
    global _bedrock_client
    if _bedrock_client is None:
        import boto3

        _bedrock_client = boto3.client("bedrock-runtime")
    return _bedrock_client


def _log(event_name: str, **details: Any) -> None:
    LOGGER.info(json.dumps({"event": event_name, **details}, separators=(",", ":")))


def _response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json", "Cache-Control": "no-store"},
        "body": json.dumps(body, ensure_ascii=False, separators=(",", ":")),
    }


def _parse_body(event: dict[str, Any]) -> dict[str, Any]:
    if event.get("isBase64Encoded"):
        raise RetrievalValidationError("body", "Base64 request bodies are not supported.")
    body = event.get("body", event)
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError as error:
            raise RetrievalValidationError("body", "Request body must be valid JSON.") from error
    if not isinstance(body, dict):
        raise RetrievalValidationError("body", "Request body must be a JSON object.")
    return body


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Answer one question using semantically retrieved document chunks."""
    request_id = getattr(context, "aws_request_id", "local")
    try:
        payload = _parse_body(event)
        question = validate_question(payload.get("question"))
        document_ids = validate_document_ids(payload.get("documentIds"))
        top_k = payload.get("topK", int(os.environ.get("RETRIEVAL_TOP_K", DEFAULT_TOP_K)))
        min_score = payload.get(
            "minScore", float(os.environ.get("RETRIEVAL_MIN_SCORE", DEFAULT_MIN_SCORE))
        )
        dimensions = int(os.environ["EMBEDDING_DIMENSIONS"])
        chunks = retrieve_chunks(
            _get_bedrock_client(),
            question=question,
            model_id=os.environ["EMBEDDING_MODEL_ID"],
            dimensions=dimensions,
            endpoint=os.environ["OPENSEARCH_COLLECTION_ENDPOINT"],
            region=os.environ.get("AWS_REGION", "us-east-1"),
            index_name=os.environ["OPENSEARCH_INDEX_NAME"],
            top_k=top_k,
            min_score=min_score,
            document_ids=document_ids,
        )
        if not chunks:
            _log("rag_no_relevant_chunks", request_id=request_id)
            return _response(
                200,
                {
                    "answer": NO_ANSWER_MESSAGE,
                    "noAnswer": True,
                    "sources": [],
                },
            )

        generated = generate_grounded_answer(
            _get_bedrock_client(),
            model_id=os.environ["GENERATION_MODEL_ID"],
            question=question,
            chunks=chunks,
            max_context_characters=int(os.environ.get("MAX_RAG_CONTEXT_CHARACTERS", "12000")),
            max_output_tokens=int(os.environ.get("MAX_ANSWER_TOKENS", "700")),
        )
        sources = [
            {
                "sourceNumber": index,
                "documentId": chunk["documentId"],
                "chunkId": chunk["chunkId"],
                "pageNumber": chunk["pageNumber"],
                "score": chunk["score"],
            }
            for index, chunk in enumerate(chunks, start=1)
        ]
        _log(
            "rag_answer_generated",
            request_id=request_id,
            source_count=len(sources),
            input_tokens=generated["usage"].get("inputTokens"),
            output_tokens=generated["usage"].get("outputTokens"),
        )
        return _response(
            200,
            {
                "answer": generated["answer"],
                "noAnswer": False,
                "sources": sources,
            },
        )
    except RetrievalValidationError as error:
        _log("rag_request_rejected", request_id=request_id, field=error.field)
        return _response(
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
        _log("rag_configuration_error", request_id=request_id, error_type=type(error).__name__)
        return _response(
            500,
            {
                "error": {
                    "code": "CONFIGURATION_ERROR",
                    "message": "The question-answering service is not configured correctly.",
                }
            },
        )
    except Exception as error:
        _log("rag_service_error", request_id=request_id, error_type=type(error).__name__)
        return _response(
            502,
            {
                "error": {
                    "code": "UPSTREAM_SERVICE_ERROR",
                    "message": "The AI service is temporarily unavailable.",
                }
            },
        )
