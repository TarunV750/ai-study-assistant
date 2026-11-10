"""Tests for the grounded question-answering Lambda."""

import json
import os
import unittest
from unittest.mock import patch

from functions.ask_question import handler
from shared.rag import NO_ANSWER_MESSAGE
from shared.retrieval import RetrievalValidationError

DOCUMENT_ID = "123e4567-e89b-42d3-a456-426614174000"


class Context:
    aws_request_id = "test-request-id"


class AskQuestionTests(unittest.TestCase):
    def setUp(self):
        handler._bedrock_client = object()
        self.environment = patch.dict(
            os.environ,
            {
                "EMBEDDING_MODEL_ID": "embedding-model",
                "EMBEDDING_DIMENSIONS": "3",
                "GENERATION_MODEL_ID": "generation-model",
                "OPENSEARCH_COLLECTION_ENDPOINT": "https://example.com",
                "OPENSEARCH_INDEX_NAME": "chunks",
                "AWS_REGION": "us-east-1",
                "RETRIEVAL_TOP_K": "5",
                "RETRIEVAL_MIN_SCORE": "0.6",
            },
            clear=False,
        )
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        handler._bedrock_client = None

    def invoke(self, payload):
        return handler.lambda_handler({"body": json.dumps(payload)}, Context())

    @patch.object(handler, "generate_grounded_answer")
    @patch.object(handler, "retrieve_chunks")
    def test_returns_grounded_answer_and_sources(self, retrieve, generate):
        retrieve.return_value = [
            {
                "documentId": DOCUMENT_ID,
                "chunkId": f"{DOCUMENT_ID}#chunk-00001",
                "chunkIndex": 0,
                "pageNumber": 4,
                "text": "Course fact",
                "score": 0.91,
            }
        ]
        generate.return_value = {
            "answer": "Course fact explained. [Source 1]",
            "usage": {"inputTokens": 50, "outputTokens": 10},
        }

        response = self.invoke({"question": "Explain the course fact."})

        self.assertEqual(response["statusCode"], 200)
        body = json.loads(response["body"])
        self.assertFalse(body["noAnswer"])
        self.assertEqual(body["sources"][0]["pageNumber"], 4)
        self.assertEqual(body["sources"][0]["sourceNumber"], 1)
        self.assertEqual(retrieve.call_args.kwargs["top_k"], 5)

    @patch.object(handler, "generate_grounded_answer")
    @patch.object(handler, "retrieve_chunks", return_value=[])
    def test_returns_no_answer_without_generation(self, retrieve, generate):
        response = self.invoke({"question": "Unknown topic"})

        self.assertEqual(response["statusCode"], 200)
        body = json.loads(response["body"])
        self.assertTrue(body["noAnswer"])
        self.assertEqual(body["answer"], NO_ANSWER_MESSAGE)
        generate.assert_not_called()

    def test_rejects_malformed_json(self):
        response = handler.lambda_handler({"body": "{"}, Context())

        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"]["field"], "body")

    def test_http_request_requires_json_content_type(self):
        response = handler.lambda_handler({"requestContext": {"http": {"method": "POST"}}, "headers": {"content-type": "text/plain"}, "body": "{}"}, Context())
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"]["field"], "contentType")

    def test_rejects_oversized_body(self):
        response = handler.lambda_handler({"body": " " * (handler.MAX_REQUEST_BODY_BYTES + 1)}, Context())
        self.assertEqual(response["statusCode"], 400)

    @patch.object(handler, "retrieve_chunks")
    def test_rejects_invalid_question(self, retrieve):
        response = self.invoke({"question": ""})

        self.assertEqual(response["statusCode"], 400)
        retrieve.assert_not_called()

    @patch.object(
        handler,
        "retrieve_chunks",
        side_effect=RetrievalValidationError("topK", "invalid"),
    )
    def test_maps_retrieval_validation_to_400(self, retrieve):
        response = self.invoke({"question": "Question", "topK": 99})

        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"]["field"], "topK")

    @patch.object(handler, "retrieve_chunks", side_effect=RuntimeError("OpenSearch unavailable"))
    def test_hides_upstream_error_details(self, retrieve):
        response = self.invoke({"question": "Question"})

        self.assertEqual(response["statusCode"], 502)
        body = json.loads(response["body"])
        self.assertEqual(body["error"]["code"], "UPSTREAM_SERVICE_ERROR")
        self.assertNotIn("OpenSearch", response["body"])


if __name__ == "__main__":
    unittest.main()
