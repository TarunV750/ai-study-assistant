"""Unit tests for semantic retrieval from OpenSearch Serverless."""

import json
import unittest

from shared import retrieval

DOCUMENT_ID = "123e4567-e89b-42d3-a456-426614174000"


class StreamingBody:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return self.payload


class FakeBedrock:
    def __init__(self, vector=None):
        self.vector = vector or [0.1, 0.2, 0.3]
        self.calls = []

    def invoke_model(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "body": StreamingBody(
                json.dumps({"embedding": self.vector}).encode("utf-8")
            )
        }


def hit(score=0.9, *, document_id=DOCUMENT_ID):
    return {
        "_score": score,
        "_source": {
            "document_id": document_id,
            "chunk_id": f"{document_id}#chunk-00001",
            "chunk_index": 0,
            "page_number": 2,
            "text": "Inheritance lets a class reuse behavior.",
        },
    }


class RetrievalTests(unittest.TestCase):
    def test_validates_question_and_document_ids(self):
        self.assertEqual(
            retrieval.validate_question("  What is inheritance?  "),
            "What is inheritance?",
        )
        self.assertEqual(
            retrieval.validate_document_ids([DOCUMENT_ID, DOCUMENT_ID]), [DOCUMENT_ID]
        )
        with self.assertRaises(retrieval.RetrievalValidationError):
            retrieval.validate_question(" ")
        with self.assertRaises(retrieval.RetrievalValidationError):
            retrieval.validate_document_ids(["not-a-uuid"])

    def test_generates_configured_query_embedding(self):
        client = FakeBedrock()

        vector = retrieval.generate_query_embedding(
            client,
            question="What is inheritance?",
            model_id="amazon.titan-embed-text-v2:0",
            dimensions=3,
        )

        self.assertEqual(vector, [0.1, 0.2, 0.3])
        request = json.loads(client.calls[0]["body"])
        self.assertEqual(request["inputText"], "What is inheritance?")
        self.assertEqual(request["dimensions"], 3)
        self.assertTrue(request["normalize"])

    def test_rejects_invalid_embedding_vector(self):
        with self.assertRaisesRegex(RuntimeError, "invalid query embedding vector"):
            retrieval.generate_query_embedding(
                FakeBedrock([0.1, float("nan"), 0.3]),
                question="Question",
                model_id="model",
                dimensions=3,
            )

    def test_searches_with_document_filter_and_score_threshold(self):
        calls = []

        def request(**kwargs):
            calls.append(kwargs)
            return {"hits": {"hits": [hit(0.91), hit(0.4)]}}

        results = retrieval.search_chunks(
            endpoint="https://collection.us-east-1.aoss.amazonaws.com",
            region="us-east-1",
            index_name="study-assistant-chunks",
            vector=[0.1, 0.2, 0.3],
            top_k=5,
            min_score=0.6,
            document_ids=[DOCUMENT_ID],
            request=request,
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["pageNumber"], 2)
        query = json.loads(calls[0]["body"])
        knn = query["query"]["knn"]["chunk_vector"]
        self.assertEqual(knn["k"], 5)
        self.assertEqual(knn["filter"], {"terms": {"document_id": [DOCUMENT_ID]}})
        self.assertNotIn("chunk_vector", query["_source"]["includes"])

    def test_search_without_document_filter_omits_filter_clause(self):
        captured = {}

        def request(**kwargs):
            captured.update(json.loads(kwargs["body"]))
            return {"hits": {"hits": []}}

        results = retrieval.search_chunks(
            endpoint="https://collection.us-east-1.aoss.amazonaws.com",
            region="us-east-1",
            index_name="chunks",
            vector=[0.1],
            request=request,
        )

        self.assertEqual(results, [])
        self.assertNotIn("filter", captured["query"]["knn"]["chunk_vector"])

    def test_rejects_invalid_top_k_and_score(self):
        for kwargs in ({"top_k": 0}, {"top_k": 11}, {"min_score": 1.1}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(retrieval.RetrievalValidationError):
                    retrieval.search_chunks(
                        endpoint="https://example.com",
                        region="us-east-1",
                        index_name="chunks",
                        vector=[0.1],
                        request=lambda **unused: {},
                        **kwargs,
                    )

    def test_rejects_malformed_search_response(self):
        with self.assertRaisesRegex(RuntimeError, "invalid search response"):
            retrieval.search_chunks(
                endpoint="https://example.com",
                region="us-east-1",
                index_name="chunks",
                vector=[0.1],
                request=lambda **unused: {"unexpected": True},
            )

    def test_retrieve_orchestrates_embedding_and_search(self):
        client = FakeBedrock()

        results = retrieval.retrieve_chunks(
            client,
            question="What is inheritance?",
            model_id="embedding-model",
            dimensions=3,
            endpoint="https://example.com",
            region="us-east-1",
            index_name="chunks",
            document_ids=[DOCUMENT_ID],
            request=lambda **unused: {"hits": {"hits": [hit()]}},
        )

        self.assertEqual(results[0]["documentId"], DOCUMENT_ID)
        self.assertEqual(len(client.calls), 1)


if __name__ == "__main__":
    unittest.main()
