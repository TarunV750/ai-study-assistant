"""Validated Bedrock embedding and OpenSearch semantic retrieval logic."""

from __future__ import annotations

import json
import math
import re
from typing import Any, Callable

from shared.opensearch import signed_json_request

DEFAULT_TOP_K = 5
DEFAULT_MIN_SCORE = 0.6
MAX_TOP_K = 10
MAX_DOCUMENT_FILTERS = 20
MAX_QUESTION_CHARACTERS = 2_000
DOCUMENT_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


class RetrievalValidationError(ValueError):
    """The semantic retrieval request or service response is invalid."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


def validate_question(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RetrievalValidationError("question", "A non-empty question is required.")
    question = value.strip()
    if len(question) > MAX_QUESTION_CHARACTERS:
        raise RetrievalValidationError(
            "question", f"Question must be {MAX_QUESTION_CHARACTERS} characters or fewer."
        )
    if any(ord(character) < 32 and character not in "\n\t" for character in question):
        raise RetrievalValidationError("question", "Question contains control characters.")
    return question


def validate_document_ids(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_DOCUMENT_FILTERS:
        raise RetrievalValidationError(
            "documentIds", f"documentIds must contain at most {MAX_DOCUMENT_FILTERS} IDs."
        )
    document_ids: list[str] = []
    for item in value:
        if not isinstance(item, str) or not DOCUMENT_ID_PATTERN.fullmatch(item):
            raise RetrievalValidationError("documentIds", "A document ID is invalid.")
        if item not in document_ids:
            document_ids.append(item)
    return document_ids


def generate_query_embedding(
    bedrock_client: Any,
    *,
    question: str,
    model_id: str,
    dimensions: int,
    normalize: bool = True,
) -> list[float]:
    response = bedrock_client.invoke_model(
        modelId=model_id,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(
            {"inputText": question, "dimensions": dimensions, "normalize": normalize},
            separators=(",", ":"),
        ).encode("utf-8"),
    )
    try:
        payload = json.loads(response["body"].read())
        vector = payload["embedding"]
    except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("Bedrock returned an invalid query embedding response.") from error
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
        raise RuntimeError("Bedrock returned an invalid query embedding vector.")
    return [float(value) for value in vector]


def _search_body(
    vector: list[float], *, top_k: int, document_ids: list[str]
) -> dict[str, Any]:
    knn: dict[str, Any] = {"vector": vector, "k": top_k}
    if document_ids:
        knn["filter"] = {"terms": {"document_id": document_ids}}
    return {
        "size": top_k,
        "_source": {
            "includes": [
                "document_id",
                "filename",
                "chunk_id",
                "chunk_index",
                "page_number",
                "text",
            ]
        },
        "query": {"knn": {"chunk_vector": knn}},
    }


def search_chunks(
    *,
    endpoint: str,
    region: str,
    index_name: str,
    vector: list[float],
    top_k: int = DEFAULT_TOP_K,
    min_score: float = DEFAULT_MIN_SCORE,
    document_ids: list[str] | None = None,
    request: Callable[..., dict[str, Any]] = signed_json_request,
) -> list[dict[str, Any]]:
    if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= MAX_TOP_K:
        raise RetrievalValidationError("topK", f"topK must be between 1 and {MAX_TOP_K}.")
    if (
        isinstance(min_score, bool)
        or not isinstance(min_score, (int, float))
        or not math.isfinite(min_score)
        or not 0 <= min_score <= 1
    ):
        raise RetrievalValidationError("minScore", "minScore must be between 0 and 1.")
    filters = validate_document_ids(document_ids)
    body = json.dumps(
        _search_body(vector, top_k=top_k, document_ids=filters), separators=(",", ":")
    ).encode("utf-8")
    response = request(
        endpoint=endpoint,
        region=region,
        method="POST",
        path=f"{index_name}/_search",
        body=body,
    )
    try:
        hits = response["hits"]["hits"]
    except (KeyError, TypeError) as error:
        raise RuntimeError("OpenSearch returned an invalid search response.") from error
    if not isinstance(hits, list):
        raise RuntimeError("OpenSearch returned an invalid search response.")

    results: list[dict[str, Any]] = []
    for hit in hits:
        if not isinstance(hit, dict):
            raise RuntimeError("OpenSearch returned an invalid search hit.")
        score = hit.get("_score")
        source = hit.get("_source")
        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(score)
            or not isinstance(source, dict)
        ):
            raise RuntimeError("OpenSearch returned an invalid search hit.")
        required = (
            source.get("document_id"),
            source.get("chunk_id"),
            source.get("chunk_index"),
            source.get("page_number"),
            source.get("text"),
        )
        if (
            not isinstance(required[0], str)
            or not DOCUMENT_ID_PATTERN.fullmatch(required[0])
            or not isinstance(required[1], str)
            or isinstance(required[2], bool)
            or not isinstance(required[2], int)
            or isinstance(required[3], bool)
            or not isinstance(required[3], int)
            or not isinstance(required[4], str)
            or not required[4].strip()
        ):
            raise RuntimeError("OpenSearch returned an invalid search hit.")
        if score < min_score:
            continue
        results.append(
            {
                "documentId": required[0],
                "filename": source.get("filename", "document.pdf") if isinstance(source.get("filename", "document.pdf"), str) else "document.pdf",
                "chunkId": required[1],
                "chunkIndex": required[2],
                "pageNumber": required[3],
                "text": required[4],
                "score": round(float(score), 6),
            }
        )
    return results


def retrieve_chunks(
    bedrock_client: Any,
    *,
    question: Any,
    model_id: str,
    dimensions: int,
    endpoint: str,
    region: str,
    index_name: str,
    top_k: int = DEFAULT_TOP_K,
    min_score: float = DEFAULT_MIN_SCORE,
    document_ids: Any = None,
    request: Callable[..., dict[str, Any]] = signed_json_request,
) -> list[dict[str, Any]]:
    validated_question = validate_question(question)
    filters = validate_document_ids(document_ids)
    vector = generate_query_embedding(
        bedrock_client,
        question=validated_question,
        model_id=model_id,
        dimensions=dimensions,
    )
    return search_chunks(
        endpoint=endpoint,
        region=region,
        index_name=index_name,
        vector=vector,
        top_k=top_k,
        min_score=min_score,
        document_ids=filters,
        request=request,
    )
