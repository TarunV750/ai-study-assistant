# Phase 5 Development Deployment

- **Date:** 2026-10-10 local time / 2026-10-11 UTC
- **Region:** `us-east-1`
- **Foundation stack:** `ai-study-assistant-dev-foundation` — `UPDATE_COMPLETE`
- **Processing function:** `ai-study-assistant-dev-process-document` — `Active`
- **Template validation:** local `cfn-lint` and AWS CloudFormation validation
  passed

## Reviewed changes

The reviewed change set updated the processing Lambda code and environment in
place. CloudFormation also reported a conditional replacement of the Lambda
invocation permission because it is dynamically linked to the EventBridge rule.
It did not replace the document bucket, processing Lambda, or event rule, and it
contained no data-resource deletion.

After a tested word-boundary refinement, the final content-derived processing
artifact key was `lambdas/process-document/5141f4865e922101.zip`. Both updates
completed in place. The deployed defaults are:

- chunk size: 1,200 characters;
- chunk overlap: 200 characters; and
- maximum chunks per document: 5,000.

## Live verification

A real two-page PDF containing 2,063 extracted characters was uploaded through
the existing S3 event path. The asynchronous processor produced:

- final status `CHUNKED`;
- page count 2 and chunk count 3;
- two overlapping page-1 chunks with source ranges `0..1189` and `991..2034`;
- one page-2 chunk with source range `0..29`;
- deterministic IDs ending in `chunk-00001` through `chunk-00003`; and
- exact chunk text matching its recorded source-page offsets, with every chunk
  beginning at a word boundary when the page contains whitespace; and
- a structured CloudWatch `document_chunked` event with matching counts.

The function remained active on Python 3.12, arm64, 512 MB, and a 60-second
timeout. The test upload and all generated processing objects were deleted after
verification. Account identifiers and credentials are intentionally excluded.

## Automated tests

Twenty-five unit tests pass. The nine new Phase 5 tests cover short pages,
overlap, readable boundaries, hard splits for long tokens, page isolation,
blank-page handling, deterministic metadata, configuration validation, chunk
limits, output ordering, and transient-failure behavior through the integrated
processor.
