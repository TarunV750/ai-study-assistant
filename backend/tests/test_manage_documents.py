"""Tests for read-only document listing and status endpoints."""

import json
import os
import unittest
from unittest.mock import patch

from functions.manage_documents import handler

DOCUMENT_ID = "123e4567-e89b-42d3-a456-426614174000"
BUCKET = "private-documents-bucket"


class StreamingBody:
    def __init__(self, data):
        self.data = data

    def read(self, amount=None):
        return self.data if amount is None else self.data[:amount]


class FakeS3:
    def __init__(self):
        self.status = {
            "schemaVersion": 1,
            "documentId": DOCUMENT_ID,
            "status": "INDEXED",
            "chunkCount": 4,
            "updatedAt": "2026-11-10T12:00:00+00:00",
        }

    def list_objects_v2(self, **kwargs):
        return {
            "Contents": [
                {"Key": f"processing/{DOCUMENT_ID}/chunks.json"},
                {"Key": f"processing/{DOCUMENT_ID}/status.json"},
            ]
        }

    def get_object(self, **kwargs):
        data = json.dumps(self.status).encode("utf-8")
        return {"ContentLength": len(data), "Body": StreamingBody(data)}

    def head_object(self, **kwargs):
        return {"Metadata": {"original-filename": "Lecture%201.pdf"}}


class Context:
    aws_request_id = "test-request-id"


def event(path_parameters=None, method="GET"):
    value = {"requestContext": {"http": {"method": method}}}
    if path_parameters is not None:
        value["pathParameters"] = path_parameters
    return value


class ManageDocumentsTests(unittest.TestCase):
    def setUp(self):
        self.s3 = FakeS3()
        handler._s3_client = self.s3
        self.environment = patch.dict(
            os.environ, {"DOCUMENTS_BUCKET_NAME": BUCKET}, clear=False
        )
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        handler._s3_client = None

    def test_lists_documents_with_filename_and_status(self):
        response = handler.lambda_handler(event(), Context())

        self.assertEqual(response["statusCode"], 200)
        body = json.loads(response["body"])
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["documents"][0]["filename"], "Lecture 1.pdf")
        self.assertEqual(body["documents"][0]["status"], "INDEXED")

    def test_returns_one_document(self):
        response = handler.lambda_handler(
            event({"documentId": DOCUMENT_ID}), Context()
        )

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(json.loads(response["body"])["chunkCount"], 4)

    def test_rejects_invalid_document_id(self):
        response = handler.lambda_handler(
            event({"documentId": "invalid"}), Context()
        )

        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(
            json.loads(response["body"])["error"]["code"], "INVALID_DOCUMENT_ID"
        )

    def test_rejects_non_get_method(self):
        response = handler.lambda_handler(event(method="DELETE"), Context())

        self.assertEqual(response["statusCode"], 405)

    def test_storage_failure_returns_safe_502(self):
        self.s3.list_objects_v2 = lambda **kwargs: (_ for _ in ()).throw(
            RuntimeError("private storage detail")
        )

        response = handler.lambda_handler(event(), Context())

        self.assertEqual(response["statusCode"], 502)
        self.assertNotIn("private storage detail", response["body"])


if __name__ == "__main__":
    unittest.main()
