# Architecture Notes

## Boundaries

The project is split into four primary boundaries:

1. `frontend` owns browser behavior and contains no AWS credentials.
2. `backend/functions` owns Lambda entry points and transport concerns.
3. `backend/shared` owns reusable domain logic and AWS service adapters.
4. `infrastructure` owns deployable AWS resources and permissions.

## Target data flow

Uploads travel directly from the browser to a private S3 bucket using a
short-lived presigned POST. S3 publishes Object Created events to EventBridge,
whose prefix-filtered rule invokes the processing Lambda. The processor
validates each object and writes page-aware extracted text, overlapping chunks,
and a status record back to a separate S3 prefix. Creating `chunks.json`
triggers a separate embedding Lambda, which invokes Amazon Bedrock and writes
validated vectors to `embeddings.json`. This path is implemented.

Creating `embeddings.json` triggers a dedicated indexing Lambda. It validates
the matching chunks and vectors, creates the vector index when needed, and uses
deterministic IDs to bulk-write searchable documents and metadata. The Amazon
OpenSearch Serverless collection, security policies, index creation, and write
path are implemented.

For questions, an API Lambda embeds the query with Titan Text Embeddings V2,
runs semantic vector search in OpenSearch Serverless, builds a prompt from
relevant chunks, and invokes Nova Micro through Bedrock Converse. The response
returns the answer plus only the filename/page sources actually cited by the
model. A separate study Lambda creates summaries, concepts, practice questions,
and study guides from explicitly selected documents.

## Design principles

- Keep handlers thin and domain logic independently testable.
- Put cloud-specific calls behind small adapters.
- Make model IDs and resource identifiers configuration, not source constants.
- Treat documents, filenames, API bodies, and retrieved text as untrusted input.
- Prefer observable failures over silent fallback behavior.
- Do not claim cloud behavior is working until it is deployed and exercised.

## Implemented extraction boundary

The processing Lambda accepts only the generated
`uploads/<uuid>/document.pdf` key shape and matching upload metadata. It limits
file size, page count, and extracted characters; rejects encrypted and
image-only documents; and preserves page numbers for later citations. The
Lambda role reads only the upload prefix and writes only the processing prefix.

## Implemented chunking boundary

Chunking is character-based and configurable, with defaults of 1,200 maximum
characters and 200 overlap characters. It prefers nearby whitespace, never
combines two pages, skips empty pages, and stores zero-based source offsets.
Deterministic chunk IDs make later indexing idempotent. A 5,000-chunk default
limit bounds output size before the embedding stage.

## Implemented embedding boundary

The embedding Lambda accepts only `processing/<uuid>/chunks.json` events and
waits for the matching `CHUNKED` completion status before making model calls.
Its role can read only chunk and status artifacts, write only embedding and
status artifacts, and invoke only the configured foundation model. The default Titan Text
Embeddings V2 request produces normalized 1,024-dimensional vectors. Model ID,
dimensions, normalization, maximum chunks, and input artifact size are
deployment configuration.

## Implemented vector-search boundary

The vector collection is attached to a next-generation collection group that
can scale indexing and search capacity to zero while idle and caps each at two
OCUs. It uses the next-generation group's required high-availability behavior,
an AWS-owned encryption key, the standard vector-index path, and an
authenticated public API endpoint. Public network
reachability does not grant data access: the data policy names only the
indexing, question, and study roles. Each role receives the required
collection-scoped IAM data-plane permission, while the data policy separates
write/update access from read-only retrieval on one exact index.

## Implemented API and grounding boundary

API Gateway exposes upload instructions, document status, question answering,
and study generation. Exact-origin CORS, throttling, access logs, body limits,
JSON content checks, and safe error responses protect the HTTP boundary. The
development API is intentionally unauthenticated and is not a multi-tenant
production boundary.

The RAG system uses a stricter relevance floor for narrow questions and a broad
top-10 policy for study material from explicitly selected documents. Retrieved
text is delimited as untrusted data. Generated output must contain valid source
markers before the API returns it.

## Implemented indexing boundary

The indexing Lambda accepts only `processing/<uuid>/embeddings.json` events and
waits for the matching `EMBEDDED` status. It joins each embedding to a validated
source chunk, ensures the 1,024-dimension cosine index exists, and writes
bounded bulk batches. Deterministic chunk IDs make retries idempotent. Permanent
input failures become `FAILED` indexing statuses; transient service errors are
raised for EventBridge retry.
