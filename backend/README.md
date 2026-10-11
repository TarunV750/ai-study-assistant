# Backend

Python Lambda handlers live in `functions`, while reusable domain and AWS
integration code lives in `shared`. Unit tests live in `tests` and mock AWS
boundaries where appropriate.

Three handlers are currently implemented:

- `create_upload_url` validates client metadata and issues a constrained,
  five-minute S3 presigned POST.
- `process_document` receives S3 events through EventBridge, validates the
  uploaded object, extracts page-aware text with `pypdf`, creates configurable
  overlapping chunks, and records a structured success or failure status in S3.
- `generate_embeddings` validates completed chunk artifacts, invokes the
  configured Amazon Bedrock embedding model once per chunk, validates every
  vector, and records the vectors and final status in S3.

The pure chunking logic lives in `shared/chunking.py`. Chunks never cross page
boundaries and include deterministic IDs, page numbers, and source character
offsets. The processor still deliberately excludes OCR and rejects encrypted,
malformed, oversized, excessively long, and image-only PDFs.

Embedding generation is a separate asynchronous boundary so its Bedrock
permission, five-minute timeout, retry behavior, and cost can be managed without
expanding the PDF processor's role. The deployed default is Amazon Titan Text
Embeddings V2 with normalized 1,024-dimensional vectors.
