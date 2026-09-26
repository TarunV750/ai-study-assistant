"""Unit tests for the presigned PDF upload Lambda."""

import json
import os
import unittest
from unittest.mock import patch

from functions.create_upload_url import handler


class FakeS3Client:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def generate_presigned_post(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {
            "url": "https://example-bucket.s3.amazonaws.com",
            "fields": {"key": kwargs["Key"], **kwargs["Fields"]},
        }


class Context:
    aws_request_id = "test-request-id"


class CreateUploadUrlTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeS3Client()
        handler._s3_client = self.client
        self.environment = patch.dict(
            os.environ,
            {
                "DOCUMENTS_BUCKET_NAME": "private-documents-bucket",
                "MAX_UPLOAD_SIZE_BYTES": "10485760",
                "UPLOAD_URL_EXPIRATION_SECONDS": "300",
            },
            clear=False,
        )
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        handler._s3_client = None

    def invoke(self, payload):
        return handler.lambda_handler({"body": json.dumps(payload)}, Context())

    def test_valid_pdf_returns_constrained_presigned_post(self):
        response = self.invoke(
            {
                "filename": "Lecture 01.pdf",
                "contentType": "application/pdf",
                "fileSize": 4096,
                "sessionId": "student-session_1",
            }
        )

        self.assertEqual(response["statusCode"], 200)
        body = json.loads(response["body"])
        self.assertEqual(body["upload"]["method"], "POST")
        self.assertEqual(body["requirements"]["maxSizeBytes"], 10485760)
        self.assertRegex(body["documentId"], r"^[0-9a-f-]{36}$")
        self.assertEqual(body["objectKey"], f"uploads/{body['documentId']}/document.pdf")

        call = self.client.calls[0]
        self.assertEqual(call["Bucket"], "private-documents-bucket")
        self.assertEqual(call["ExpiresIn"], 300)
        self.assertEqual(call["Fields"]["Content-Type"], "application/pdf")
        self.assertEqual(call["Fields"]["x-amz-server-side-encryption"], "AES256")
        self.assertEqual(call["Fields"]["x-amz-meta-original-filename"], "Lecture%2001.pdf")
        self.assertIn(["content-length-range", 1, 10485760], call["Conditions"])

    def test_direct_invocation_payload_is_supported(self):
        response = handler.lambda_handler(
            {"filename": "notes.pdf", "contentType": "application/pdf", "fileSize": 10},
            Context(),
        )
        self.assertEqual(response["statusCode"], 200)

    def test_malformed_json_is_rejected(self):
        response = handler.lambda_handler({"body": "{"}, Context())
        body = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(body["error"]["field"], "body")
        self.assertEqual(self.client.calls, [])

    def test_non_pdf_filename_is_rejected(self):
        response = self.invoke(
            {"filename": "notes.txt", "contentType": "application/pdf", "fileSize": 100}
        )
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"]["field"], "filename")

    def test_path_filename_is_rejected(self):
        response = self.invoke(
            {"filename": "../notes.pdf", "contentType": "application/pdf", "fileSize": 100}
        )
        self.assertEqual(response["statusCode"], 400)

    def test_wrong_content_type_is_rejected(self):
        response = self.invoke(
            {"filename": "notes.pdf", "contentType": "text/plain", "fileSize": 100}
        )
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"]["field"], "contentType")

    def test_zero_oversized_and_boolean_sizes_are_rejected(self):
        for file_size in (0, 10485761, True):
            with self.subTest(file_size=file_size):
                response = self.invoke(
                    {
                        "filename": "notes.pdf",
                        "contentType": "application/pdf",
                        "fileSize": file_size,
                    }
                )
                self.assertEqual(response["statusCode"], 400)
                self.assertEqual(json.loads(response["body"])["error"]["field"], "fileSize")

    def test_invalid_session_id_is_rejected(self):
        response = self.invoke(
            {
                "filename": "notes.pdf",
                "contentType": "application/pdf",
                "fileSize": 100,
                "sessionId": "not a safe id",
            }
        )
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"]["field"], "sessionId")

    def test_s3_signing_failure_returns_502(self):
        handler._s3_client = FakeS3Client(RuntimeError("simulated failure"))
        response = self.invoke(
            {"filename": "notes.pdf", "contentType": "application/pdf", "fileSize": 100}
        )
        body = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 502)
        self.assertEqual(body["error"]["code"], "STORAGE_ERROR")


if __name__ == "__main__":
    unittest.main()
