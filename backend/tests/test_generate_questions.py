import json
import os
import unittest
from unittest.mock import patch

from functions.generate_questions import handler


class GenerateQuestionsHandlerTests(unittest.TestCase):
    def setUp(self):
        os.environ.update({"EMBEDDING_MODEL_ID": "embed", "EMBEDDING_DIMENSIONS": "1024", "OPENSEARCH_COLLECTION_ENDPOINT": "https://example.com", "OPENSEARCH_INDEX_NAME": "index", "GENERATION_MODEL_ID": "generate"})

    @patch.object(handler, "_client", return_value=object())
    @patch.object(handler, "generate_study_material")
    @patch.object(handler, "retrieve_chunks")
    def test_returns_generated_material(self, retrieve, generate, _client):
        retrieve.return_value = [{"documentId": "9b8c7d6e-5f4a-43b2-8c7d-6e5f4a3b2c1d", "chunkId": "c1", "pageNumber": 1, "text": "text", "score": .9}]
        generate.return_value = {"title": "Course summary", "content": "Summary [Source 1]", "usage": {}}
        response = handler.lambda_handler({"body": json.dumps({"mode": "summary"})}, None)
        self.assertEqual(response["statusCode"], 200)
        self.assertFalse(json.loads(response["body"])["noAnswer"])

    def test_rejects_bad_mode(self):
        response = handler.lambda_handler({"body": json.dumps({"mode": "essay"})}, None)
        self.assertEqual(response["statusCode"], 400)

    def test_http_request_requires_json_content_type(self):
        response = handler.lambda_handler({"requestContext": {"http": {"method": "POST"}}, "headers": {"content-type": "text/plain"}, "body": "{}"}, None)
        self.assertEqual(response["statusCode"], 400)

    @patch.object(handler, "_client", return_value=object())
    @patch.object(handler, "generate_study_material", return_value={"title": "Course summary", "content": "Uncited material", "usage": {}})
    @patch.object(handler, "retrieve_chunks", return_value=[{"documentId": "9b8c7d6e-5f4a-43b2-8c7d-6e5f4a3b2c1d", "chunkId": "c1", "pageNumber": 1, "text": "text", "score": .9}])
    def test_rejects_uncited_study_output(self, retrieve, generate, client):
        response = handler.lambda_handler({"body": json.dumps({"mode": "summary"})}, None)
        self.assertEqual(response["statusCode"], 502)
        self.assertEqual(json.loads(response["body"])["error"]["code"], "UNGROUNDED_MODEL_RESPONSE")


if __name__ == "__main__":
    unittest.main()
