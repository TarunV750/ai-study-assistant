# Backend

Python Lambda handlers live in `functions`, while reusable domain and AWS
integration code lives in `shared`. Unit tests live in `tests` and mock AWS
boundaries where appropriate.

Two handlers are currently implemented:

- `create_upload_url` validates client metadata and issues a constrained,
  five-minute S3 presigned POST.
- `process_document` receives S3 events through EventBridge, validates the
  uploaded object, extracts page-aware text with `pypdf`, creates configurable
  overlapping chunks, and records a structured success or failure status in S3.

The pure chunking logic lives in `shared/chunking.py`. Chunks never cross page
boundaries and include deterministic IDs, page numbers, and source character
offsets. The processor still deliberately excludes OCR and rejects encrypted,
malformed, oversized, excessively long, and image-only PDFs.
