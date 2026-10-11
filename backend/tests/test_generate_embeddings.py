"""Tests for the asynchronous Amazon Bedrock embedding Lambda."""

import json
import os
import unittest
from unittest.mock import patch

from functions.generate_embeddings import handler

DOCUMENT_ID = "123e4567-e89b-42d3-a456-426614174000"
CHUNKS_KEY = f"processing/{DOCUMENT_ID}/chunks.json"
BUCKET = "private-documents-bucket"


def chunks_artifact(count=2):
    chunks = []
    for index in range(count):
        text = f"Chunk text number {index + 1}"
        chunks.append(
            {
                "chunkId": f"{DOCUMENT_ID}#chunk-{index + 1:05d}",
                "chunkIndex": index,
                "pageNumber": index + 1,
                "characterCount": len(text),
                "text": text,
            }
        )
    return {
        "schemaVersion": 1,
        "documentId": DOCUMENT_ID,
        "status": "CHUNKED",
        "chunkCount": count,
        "chunks": chunks,
    }


def event_for(size):
    return {
        "source": "aws.s3",
        "detail-type": "Object Created",
        "detail": {
            "bucket": {"name": BUCKET},
            "object": {"key": CHUNKS_KEY, "size": size, "etag": "chunks-etag"},
        },
    }


def chunked_status():
    return {
        "schemaVersion": 1,
        "documentId": DOCUMENT_ID,
        "status": "CHUNKED",
        "chunksKey": CHUNKS_KEY,
    }


class StreamingBody:
    def __init__(self, data):
        self.data = data

    def read(self, amount=None):
        return self.data if amount is None else self.data[:amount]


class FakeS3Client:
    def __init__(self, artifact, *, status=None):
        self.data = (
            artifact
            if isinstance(artifact, bytes)
            else json.dumps(artifact, separators=(",", ":")).encode("utf-8")
        )
        self.status_data = json.dumps(status or chunked_status()).encode("utf-8")
        self.puts = []

    def get_object(self, **kwargs):
        data = self.status_data if kwargs["Key"].endswith("/status.json") else self.data
        return {"ContentLength": len(data), "Body": StreamingBody(data)}

    def put_object(self, **kwargs):
        self.puts.append(kwargs)
        return {"ETag": "result-etag"}


class FakeBedrockClient:
    def __init__(self, *, vector=None):
        self.vector = vector or [0.1, 0.2, 0.3]
        self.calls = []

    def invoke_model(self, **kwargs):
        self.calls.append(kwargs)
        response = {
            "embedding": self.vector,
            "inputTextTokenCount": 5,
        }
        return {"body": StreamingBody(json.dumps(response).encode("utf-8"))}


class Context:
    aws_request_id = "test-request-id"


class GenerateEmbeddingsTests(unittest.TestCase):
    def setUp(self):
        self.artifact = chunks_artifact()
        self.s3 = FakeS3Client(self.artifact)
        self.bedrock = FakeBedrockClient()
        handler._s3_client = self.s3
        handler._bedrock_client = self.bedrock
        self.environment = patch.dict(
            os.environ,
            {
                "DOCUMENTS_BUCKET_NAME": BUCKET,
                "EMBEDDING_MODEL_ID": "amazon.titan-embed-text-v2:0",
                "EMBEDDING_DIMENSIONS": "3",
                "NORMALIZE_EMBEDDINGS": "true",
                "MAX_EMBEDDING_CHUNKS": "500",
                "MAX_CHUNKS_FILE_SIZE_BYTES": "52428800",
            },
            clear=False,
        )
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        handler._s3_client = None
        handler._bedrock_client = None

    def stored_json(self, key):
        item = next(call for call in self.s3.puts if call["Key"] == key)
        self.assertEqual(item["ServerSideEncryption"], "AES256")
        self.assertEqual(item["ContentType"], "application/json")
        return json.loads(item["Body"])

    def test_embeds_every_chunk_and_writes_status_last(self):
        response = handler.lambda_handler(event_for(len(self.s3.data)), Context())

        embeddings_key = f"processing/{DOCUMENT_ID}/embeddings.json"
        status_key = f"processing/{DOCUMENT_ID}/status.json"
        self.assertEqual(response["status"], "EMBEDDED")
        self.assertEqual(response["chunkCount"], 2)
        self.assertEqual(
            [call["Key"] for call in self.s3.puts],
            [embeddings_key, status_key],
        )
        self.assertEqual(len(self.bedrock.calls), 2)

        request = json.loads(self.bedrock.calls[0]["body"])
        self.assertEqual(request["dimensions"], 3)
        self.assertEqual(request["normalize"], True)
        self.assertEqual(request["inputText"], "Chunk text number 1")

        embedded = self.stored_json(embeddings_key)
        self.assertEqual(embedded["modelId"], "amazon.titan-embed-text-v2:0")
        self.assertEqual(embedded["dimensions"], 3)
        self.assertEqual(embedded["embeddings"][0]["embedding"], [0.1, 0.2, 0.3])
        self.assertEqual(embedded["embeddings"][1]["pageNumber"], 2)

    def test_ignores_objects_that_are_not_chunk_artifacts(self):
        event = event_for(len(self.s3.data))
        event["detail"]["object"]["key"] = f"processing/{DOCUMENT_ID}/status.json"

        response = handler.lambda_handler(event, Context())

        self.assertEqual(response["status"], "IGNORED")
        self.assertEqual(self.bedrock.calls, [])
        self.assertEqual(self.s3.puts, [])

    def test_rejects_invalid_chunk_schema_and_records_failure(self):
        self.artifact["documentId"] = "different"
        self.s3 = FakeS3Client(self.artifact)
        handler._s3_client = self.s3

        response = handler.lambda_handler(event_for(len(self.s3.data)), Context())

        self.assertEqual(response["status"], "FAILED")
        self.assertEqual(response["stage"], "EMBEDDING")
        self.assertEqual(response["error"]["code"], "INVALID_CHUNKS_SCHEMA")
        self.assertEqual(self.bedrock.calls, [])

    def test_rejects_document_above_embedding_chunk_limit(self):
        with patch.dict(os.environ, {"MAX_EMBEDDING_CHUNKS": "1"}):
            response = handler.lambda_handler(event_for(len(self.s3.data)), Context())

        self.assertEqual(response["error"]["code"], "TOO_MANY_EMBEDDING_CHUNKS")
        self.assertEqual(self.bedrock.calls, [])

    def test_invalid_json_records_failure(self):
        self.s3 = FakeS3Client(b"not-json")
        handler._s3_client = self.s3

        response = handler.lambda_handler(event_for(len(self.s3.data)), Context())

        self.assertEqual(response["error"]["code"], "INVALID_CHUNKS_JSON")
        self.assertEqual(len(self.s3.puts), 1)

    def test_bedrock_failure_is_raised_for_eventbridge_retry(self):
        self.bedrock.invoke_model = lambda **kwargs: (_ for _ in ()).throw(
            RuntimeError("temporary Bedrock failure")
        )

        with self.assertRaisesRegex(RuntimeError, "temporary Bedrock failure"):
            handler.lambda_handler(event_for(len(self.s3.data)), Context())

        self.assertEqual(self.s3.puts, [])

    def test_waits_for_chunking_completion_status_before_embedding(self):
        self.s3 = FakeS3Client(self.artifact, status={"status": "PROCESSING"})
        handler._s3_client = self.s3

        with self.assertRaisesRegex(RuntimeError, "not ready"):
            handler.lambda_handler(event_for(len(self.s3.data)), Context())

        self.assertEqual(self.bedrock.calls, [])
        self.assertEqual(self.s3.puts, [])

    def test_invalid_embedding_vector_is_raised_for_retry(self):
        self.bedrock = FakeBedrockClient(vector=[0.1, float("nan"), 0.3])
        handler._bedrock_client = self.bedrock

        with self.assertRaisesRegex(RuntimeError, "invalid embedding vector"):
            handler.lambda_handler(event_for(len(self.s3.data)), Context())

        self.assertEqual(self.s3.puts, [])


if __name__ == "__main__":
    unittest.main()
