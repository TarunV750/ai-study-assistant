"""Tests for the OpenSearch Serverless document-indexing Lambda."""

import json
import os
import unittest
from unittest.mock import patch

from functions.index_document import handler

DOCUMENT_ID = "123e4567-e89b-42d3-a456-426614174000"
CHUNKS_KEY = f"processing/{DOCUMENT_ID}/chunks.json"
EMBEDDINGS_KEY = f"processing/{DOCUMENT_ID}/embeddings.json"
STATUS_KEY = f"processing/{DOCUMENT_ID}/status.json"
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
                "pageChunkIndex": 0,
                "startCharacter": 0,
                "endCharacter": len(text),
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


def embeddings_artifact(count=2):
    return {
        "schemaVersion": 1,
        "documentId": DOCUMENT_ID,
        "status": "EMBEDDED",
        "sourceChunksKey": CHUNKS_KEY,
        "modelId": "amazon.titan-embed-text-v2:0",
        "dimensions": 3,
        "normalized": True,
        "chunkCount": count,
        "embeddings": [
            {
                "chunkId": f"{DOCUMENT_ID}#chunk-{index + 1:05d}",
                "chunkIndex": index,
                "pageNumber": index + 1,
                "embedding": [0.1, 0.2, 0.3],
            }
            for index in range(count)
        ],
    }


def embedded_status():
    return {
        "schemaVersion": 1,
        "documentId": DOCUMENT_ID,
        "status": "EMBEDDED",
        "chunksKey": CHUNKS_KEY,
        "embeddingsKey": EMBEDDINGS_KEY,
    }


def event_for(size=100):
    return {
        "source": "aws.s3",
        "detail-type": "Object Created",
        "detail": {
            "bucket": {"name": BUCKET},
            "object": {"key": EMBEDDINGS_KEY, "size": size, "etag": "embedding-etag"},
        },
    }


class StreamingBody:
    def __init__(self, data):
        self.data = data

    def read(self, amount=None):
        return self.data if amount is None else self.data[:amount]


class FakeS3Client:
    def __init__(self, *, chunks=None, embeddings=None, status=None):
        self.objects = {
            CHUNKS_KEY: json.dumps(chunks or chunks_artifact()).encode("utf-8"),
            EMBEDDINGS_KEY: json.dumps(embeddings or embeddings_artifact()).encode("utf-8"),
            STATUS_KEY: json.dumps(status or embedded_status()).encode("utf-8"),
        }
        self.puts = []

    def get_object(self, **kwargs):
        data = self.objects[kwargs["Key"]]
        return {"ContentLength": len(data), "Body": StreamingBody(data)}

    def put_object(self, **kwargs):
        self.puts.append(kwargs)
        return {"ETag": "result-etag"}


class Context:
    aws_request_id = "test-request-id"


class IndexDocumentTests(unittest.TestCase):
    def setUp(self):
        self.s3 = FakeS3Client()
        handler._s3_client = self.s3
        self.requests = []

        def successful_request(**kwargs):
            self.requests.append(kwargs)
            operations = [
                json.loads(line)
                for line in kwargs["body"].decode("utf-8").splitlines()
            ]
            count = len(operations) // 2
            return {"errors": False, "items": [{"index": {"status": 201}}] * count}

        self.request_patch = patch.object(
            handler, "_signed_opensearch_request", side_effect=successful_request
        )
        self.request_patch.start()
        self.environment = patch.dict(
            os.environ,
            {
                "DOCUMENTS_BUCKET_NAME": BUCKET,
                "OPENSEARCH_COLLECTION_ENDPOINT": "https://collection.us-east-1.aoss.amazonaws.com",
                "OPENSEARCH_INDEX_NAME": "study-assistant-chunks",
                "AWS_REGION": "us-east-1",
                "EMBEDDING_DIMENSIONS": "3",
                "MAX_INDEX_CHUNKS": "500",
                "MAX_INDEX_ARTIFACT_SIZE_BYTES": "52428800",
                "INDEX_BULK_BATCH_SIZE": "1",
            },
            clear=False,
        )
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.request_patch.stop()
        handler._s3_client = None

    def stored_status(self):
        item = next(call for call in self.s3.puts if call["Key"] == STATUS_KEY)
        self.assertEqual(item["ServerSideEncryption"], "AES256")
        self.assertEqual(item["ContentType"], "application/json")
        return json.loads(item["Body"])

    def test_indexes_validated_chunks_in_bounded_batches_and_writes_status(self):
        response = handler.lambda_handler(event_for(), Context())

        self.assertEqual(response["status"], "INDEXED")
        self.assertEqual(response["chunkCount"], 2)
        self.assertEqual(len(self.requests), 3)
        self.assertEqual(self.requests[0]["method"], "HEAD")
        first_lines = self.requests[1]["body"].decode("utf-8").splitlines()
        action = json.loads(first_lines[0])
        document = json.loads(first_lines[1])
        self.assertEqual(action["index"]["_index"], "study-assistant-chunks")
        self.assertEqual(action["index"]["_id"], f"{DOCUMENT_ID}#chunk-00001")
        self.assertEqual(document["text"], "Chunk text number 1")
        self.assertEqual(document["chunk_vector"], [0.1, 0.2, 0.3])
        self.assertEqual(self.stored_status()["indexName"], "study-assistant-chunks")

    def test_creates_vector_index_when_it_does_not_exist(self):
        self.request_patch.stop()
        calls = []

        def create_if_missing(**kwargs):
            calls.append(kwargs)
            if kwargs["method"] == "HEAD":
                raise handler.OpenSearchRequestError(404, "missing")
            return {"acknowledged": True}

        self.request_patch = patch.object(
            handler, "_signed_opensearch_request", side_effect=create_if_missing
        )
        self.request_patch.start()

        handler._ensure_index(
            endpoint=os.environ["OPENSEARCH_COLLECTION_ENDPOINT"],
            region="us-east-1",
            index_name="study-assistant-chunks",
            dimensions=3,
        )

        self.assertEqual([call["method"] for call in calls], ["HEAD", "PUT"])
        definition = json.loads(calls[1]["body"])
        vector = definition["mappings"]["properties"]["chunk_vector"]
        self.assertEqual(vector["dimension"], 3)
        self.assertEqual(vector["space_type"], "cosinesimil")

    def test_ignores_objects_that_are_not_embedding_artifacts(self):
        event = event_for()
        event["detail"]["object"]["key"] = STATUS_KEY

        response = handler.lambda_handler(event, Context())

        self.assertEqual(response["status"], "IGNORED")
        self.assertEqual(self.requests, [])
        self.assertEqual(self.s3.puts, [])

    def test_waits_for_embedding_completion_status(self):
        self.s3 = FakeS3Client(status={"status": "CHUNKED"})
        handler._s3_client = self.s3

        with self.assertRaisesRegex(RuntimeError, "not ready"):
            handler.lambda_handler(event_for(), Context())

        self.assertEqual(self.requests, [])
        self.assertEqual(self.s3.puts, [])

    def test_retries_an_already_indexed_document_idempotently(self):
        indexed = embedded_status() | {
            "status": "INDEXED",
            "indexName": "study-assistant-chunks",
            "chunkCount": 2,
        }
        self.s3 = FakeS3Client(status=indexed)
        handler._s3_client = self.s3

        response = handler.lambda_handler(event_for(), Context())

        self.assertEqual(response["status"], "INDEXED")
        self.assertEqual(response["chunkCount"], 2)
        self.assertEqual(len(self.requests), 3)

    def test_rejects_mismatched_chunk_and_embedding_ids(self):
        embeddings = embeddings_artifact()
        embeddings["embeddings"][0]["chunkId"] = "different"
        self.s3 = FakeS3Client(embeddings=embeddings)
        handler._s3_client = self.s3

        response = handler.lambda_handler(event_for(), Context())

        self.assertEqual(response["status"], "FAILED")
        self.assertEqual(response["stage"], "INDEXING")
        self.assertEqual(response["error"]["code"], "MISMATCHED_INDEX_CHUNK")
        self.assertEqual(self.requests, [])

    def test_rejects_non_finite_vector(self):
        embeddings = embeddings_artifact()
        embeddings["embeddings"][0]["embedding"][1] = float("nan")
        self.s3 = FakeS3Client(embeddings=embeddings)
        handler._s3_client = self.s3

        response = handler.lambda_handler(event_for(), Context())

        self.assertEqual(response["error"]["code"], "INVALID_INDEX_CHUNK")
        self.assertEqual(self.requests, [])

    def test_rejects_document_above_index_chunk_limit(self):
        with patch.dict(os.environ, {"MAX_INDEX_CHUNKS": "1"}):
            response = handler.lambda_handler(event_for(), Context())

        self.assertEqual(response["error"]["code"], "TOO_MANY_INDEX_CHUNKS")
        self.assertEqual(self.requests, [])

    def test_opensearch_failure_is_raised_for_eventbridge_retry(self):
        self.request_patch.stop()
        self.request_patch = patch.object(
            handler,
            "_signed_opensearch_request",
            side_effect=RuntimeError("temporary OpenSearch failure"),
        )
        self.request_patch.start()

        with self.assertRaisesRegex(RuntimeError, "temporary OpenSearch failure"):
            handler.lambda_handler(event_for(), Context())

        self.assertEqual(self.s3.puts, [])


if __name__ == "__main__":
    unittest.main()
