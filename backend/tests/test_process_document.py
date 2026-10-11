"""Tests for the asynchronous PDF extraction Lambda."""

import io
import json
import os
import unittest
from unittest.mock import patch

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from functions.process_document import handler

DOCUMENT_ID = "123e4567-e89b-42d3-a456-426614174000"
UPLOAD_KEY = f"uploads/{DOCUMENT_ID}/document.pdf"
BUCKET = "private-documents-bucket"


def make_pdf(texts):
    output = io.BytesIO()
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_reference = writer._add_object(font)
    for text in texts:
        page = writer.add_blank_page(width=612, height=792)
        resources = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {NameObject("/F1"): font_reference}
                )
            }
        )
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii"))
        page[NameObject("/Resources")] = resources
        page[NameObject("/Contents")] = writer._add_object(stream)
    writer.write(output)
    return output.getvalue()


def event_for(size):
    return {
        "source": "aws.s3",
        "detail-type": "Object Created",
        "detail": {
            "bucket": {"name": BUCKET},
            "object": {"key": UPLOAD_KEY, "size": size, "etag": "test-etag"},
        },
    }


class StreamingBody:
    def __init__(self, data):
        self.data = data

    def read(self, amount=None):
        return self.data if amount is None else self.data[:amount]


class FakeS3Client:
    def __init__(self, data, *, content_type="application/pdf", metadata=None):
        self.data = data
        self.content_type = content_type
        self.metadata = metadata or {
            "document-id": DOCUMENT_ID,
            "original-filename": "Lecture%201.pdf",
            "uploaded-at": "2026-10-09T12:00:00+00:00",
            "session-id": "test-session",
        }
        self.puts = []

    def head_object(self, **kwargs):
        return {
            "ContentLength": len(self.data),
            "ContentType": self.content_type,
            "Metadata": self.metadata,
        }

    def get_object(self, **kwargs):
        return {"Body": StreamingBody(self.data)}

    def put_object(self, **kwargs):
        self.puts.append(kwargs)
        return {"ETag": "result-etag"}


class Context:
    aws_request_id = "test-request-id"


class ProcessDocumentTests(unittest.TestCase):
    def setUp(self):
        self.pdf = make_pdf(["First page", "Second page"])
        self.client = FakeS3Client(self.pdf)
        handler._s3_client = self.client
        self.environment = patch.dict(
            os.environ,
            {
                "DOCUMENTS_BUCKET_NAME": BUCKET,
                "MAX_UPLOAD_SIZE_BYTES": "10485760",
                "MAX_PDF_PAGES": "200",
                "MAX_EXTRACTED_CHARACTERS": "2000000",
                "CHUNK_SIZE_CHARACTERS": "1200",
                "CHUNK_OVERLAP_CHARACTERS": "200",
                "MAX_CHUNKS_PER_DOCUMENT": "5000",
            },
            clear=False,
        )
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        handler._s3_client = None

    def stored_json(self, key):
        item = next(call for call in self.client.puts if call["Key"] == key)
        self.assertEqual(item["ServerSideEncryption"], "AES256")
        self.assertEqual(item["ContentType"], "application/json")
        return json.loads(item["Body"])

    def test_extracts_and_chunks_page_aware_text_and_writes_status_last(self):
        response = handler.lambda_handler(event_for(len(self.pdf)), Context())

        self.assertEqual(response["status"], "CHUNKED")
        self.assertEqual(response["pageCount"], 2)
        self.assertEqual(response["chunkCount"], 2)
        extracted_key = f"processing/{DOCUMENT_ID}/extracted.json"
        chunks_key = f"processing/{DOCUMENT_ID}/chunks.json"
        status_key = f"processing/{DOCUMENT_ID}/status.json"
        self.assertEqual(
            [call["Key"] for call in self.client.puts],
            [extracted_key, chunks_key, status_key],
        )

        extracted = self.stored_json(extracted_key)
        self.assertEqual(extracted["source"]["originalFilename"], "Lecture 1.pdf")
        self.assertEqual(extracted["pages"][0], {"pageNumber": 1, "text": "First page"})
        self.assertEqual(extracted["pages"][1], {"pageNumber": 2, "text": "Second page"})

        chunked = self.stored_json(chunks_key)
        self.assertEqual(chunked["status"], "CHUNKED")
        self.assertEqual(chunked["strategy"]["pageBoundaryBehavior"], "preserve")
        self.assertEqual(
            [chunk["pageNumber"] for chunk in chunked["chunks"]],
            [1, 2],
        )

    def test_rejects_document_that_exceeds_chunk_limit(self):
        long_pdf = make_pdf(["word " * 100])
        self.client = FakeS3Client(long_pdf)
        handler._s3_client = self.client

        with patch.dict(
            os.environ,
            {
                "CHUNK_SIZE_CHARACTERS": "40",
                "CHUNK_OVERLAP_CHARACTERS": "10",
                "MAX_CHUNKS_PER_DOCUMENT": "2",
            },
        ):
            response = handler.lambda_handler(event_for(len(long_pdf)), Context())

        self.assertEqual(response["error"]["code"], "TOO_MANY_CHUNKS")
        self.assertEqual(
            [call["Key"] for call in self.client.puts],
            [f"processing/{DOCUMENT_ID}/status.json"],
        )

    def test_invalid_chunk_configuration_fails_for_operator_attention(self):
        with patch.dict(
            os.environ,
            {"CHUNK_SIZE_CHARACTERS": "100", "CHUNK_OVERLAP_CHARACTERS": "100"},
        ):
            with self.assertRaisesRegex(ValueError, "smaller than"):
                handler.lambda_handler(event_for(len(self.pdf)), Context())

        self.assertEqual(self.client.puts, [])

    def test_rejects_non_pdf_bytes_and_records_failure(self):
        self.client = FakeS3Client(b"plain text masquerading as a PDF")
        handler._s3_client = self.client

        response = handler.lambda_handler(event_for(len(self.client.data)), Context())

        self.assertEqual(response["status"], "FAILED")
        self.assertEqual(response["error"]["code"], "INVALID_PDF_SIGNATURE")
        status = self.stored_json(f"processing/{DOCUMENT_ID}/status.json")
        self.assertEqual(status["error"]["code"], "INVALID_PDF_SIGNATURE")

    def test_rejects_pdf_without_extractable_text(self):
        empty_pdf = make_pdf([""])
        self.client = FakeS3Client(empty_pdf)
        handler._s3_client = self.client

        response = handler.lambda_handler(event_for(len(empty_pdf)), Context())

        self.assertEqual(response["error"]["code"], "NO_EXTRACTABLE_TEXT")

    def test_rejects_mismatched_document_metadata(self):
        self.client = FakeS3Client(self.pdf, metadata={"document-id": "different"})
        handler._s3_client = self.client

        response = handler.lambda_handler(event_for(len(self.pdf)), Context())

        self.assertEqual(response["error"]["code"], "METADATA_MISMATCH")
        self.assertEqual(len(self.client.puts), 1)

    def test_rejects_too_many_pages_before_extraction(self):
        with patch.dict(os.environ, {"MAX_PDF_PAGES": "1"}):
            response = handler.lambda_handler(event_for(len(self.pdf)), Context())

        self.assertEqual(response["error"]["code"], "TOO_MANY_PAGES")

    def test_ignores_objects_outside_upload_contract(self):
        event = event_for(len(self.pdf))
        event["detail"]["object"]["key"] = "processing/result.json"

        response = handler.lambda_handler(event, Context())

        self.assertEqual(response["status"], "IGNORED")
        self.assertEqual(self.client.puts, [])

    def test_s3_service_failure_is_raised_for_eventbridge_retry(self):
        self.client.head_object = lambda **kwargs: (_ for _ in ()).throw(
            RuntimeError("temporary S3 failure")
        )

        with self.assertRaisesRegex(RuntimeError, "temporary S3 failure"):
            handler.lambda_handler(event_for(len(self.pdf)), Context())


if __name__ == "__main__":
    unittest.main()
