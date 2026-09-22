# Architecture Notes

## Boundaries

The project is split into four primary boundaries:

1. `frontend` owns browser behavior and contains no AWS credentials.
2. `backend/functions` owns Lambda entry points and transport concerns.
3. `backend/shared` owns reusable domain logic and AWS service adapters.
4. `infrastructure` owns deployable AWS resources and permissions.

## Target data flow

Uploads travel directly from the browser to a private S3 bucket using a
short-lived presigned URL. An S3 event starts asynchronous ingestion. The
processor extracts PDF text, splits it into overlapping chunks, requests
embeddings from Amazon Bedrock, and indexes text plus metadata in an Amazon
OpenSearch Serverless vector search collection.

For questions, an API Lambda embeds the query, runs semantic vector search in
OpenSearch Serverless, builds a prompt from relevant chunks, and invokes a
Bedrock generation model. The response returns both an answer and source
metadata. Concrete models, dimensions, thresholds, and chunking values will be
chosen and tested in their corresponding phases.

## Design principles

- Keep handlers thin and domain logic independently testable.
- Put cloud-specific calls behind small adapters.
- Make model IDs and resource identifiers configuration, not source constants.
- Treat documents, filenames, API bodies, and retrieved text as untrusted input.
- Prefer observable failures over silent fallback behavior.
- Do not claim cloud behavior is working until it is deployed and exercised.
