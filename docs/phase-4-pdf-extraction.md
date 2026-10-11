# Phase 4: Event-Driven PDF Extraction

Phase 4 turns a completed S3 upload into validated, page-aware text without
requiring the browser to invoke a second backend operation.

## Data flow

```text
uploads/<document-id>/document.pdf
                |
                v
S3 Object Created -> EventBridge rule -> process-document Lambda
                                              |
                                              v
                         processing/<document-id>/extracted.json
                         processing/<document-id>/status.json
```

S3 EventBridge delivery was selected because the existing bucket can enable it
through CloudFormation while a separate rule owns filtering and retries. The
rule filters the specific bucket and `uploads/` prefix; the Lambda still
validates the complete event and exact object-key contract as a defense in
depth.

## Validation boundary

Before parsing, the processor checks:

- the event source, event type, bucket, key shape, and positive object size;
- the authoritative S3 object length, `application/pdf` content type, and
  matching `document-id` metadata;
- the configured byte limit and a PDF signature near the start of the file;
- strict PDF parsing, encryption state, page count, and extracted text size;
- that at least one page contains extractable text.

The default limits are 10 MiB, 200 pages, and 2,000,000 extracted characters.
They are CloudFormation parameters and Lambda environment variables rather than
hard-coded deployment assumptions.

## Output contract

On success, `extracted.json` contains schema version 1, source metadata, total
page and character counts, and an ordered array of `{pageNumber, text}` values.
The processor writes `status.json` after the extraction object so consumers can
treat the status as a completion marker.

Permanent input failures write a schema-versioned `FAILED` status with a stable
error code and a safe message. Unexpected AWS or runtime failures are raised so
EventBridge can retry them up to two times within one hour. Structured
CloudWatch events distinguish extracted, rejected, ignored, and failed work.

## Current limitations

This phase extracts embedded PDF text only. It intentionally does not perform
OCR, tables-to-structure conversion, chunking, embedding, or indexing. Phase 5
will add page-aware overlapping chunking on top of the stable extraction
format. PDF parsing remains resource-intensive for hostile inputs, so file,
page, character, memory, and execution-time limits provide bounded risk; a
production system with untrusted public uploads may also isolate parsing more
strongly.
