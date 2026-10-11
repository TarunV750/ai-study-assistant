# Backend

Python Lambda handlers live in `functions`, while reusable domain and AWS
integration code lives in `shared`. Unit tests live in `tests` and mock AWS
boundaries where appropriate.

Two handlers are currently implemented:

- `create_upload_url` validates client metadata and issues a constrained,
  five-minute S3 presigned POST.
- `process_document` receives S3 events through EventBridge, validates the
  uploaded object, extracts page-aware text with `pypdf`, and records a
  structured success or failure status in S3.

The processor deliberately does not perform OCR or text chunking yet. It rejects
encrypted, malformed, oversized, excessively long, and image-only PDFs so later
pipeline stages receive a bounded and explicit input format.
