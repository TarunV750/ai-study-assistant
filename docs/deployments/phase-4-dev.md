# Phase 4 Development Deployment

- **Date:** 2026-10-10 local time / 2026-10-11 UTC
- **Region:** `us-east-1`
- **Foundation stack:** `ai-study-assistant-dev-foundation` — `UPDATE_COMPLETE`
- **Processing function:** `ai-study-assistant-dev-process-document`
- **Template validation:** local `cfn-lint` and AWS CloudFormation validation
  passed

## Reviewed changes

The reviewed change set added the document-processing Lambda, its EventBridge
invocation permission, and the upload event rule. It modified the document
bucket to publish events to EventBridge and expanded only the dedicated
processing role with these application permissions:

- `s3:GetObject` on `uploads/*`;
- `s3:PutObject` on `processing/*`; and
- writes to the function's own CloudWatch log group.

There were no resource replacements or deletions. The processing package was
uploaded under the content-derived artifact key
`lambdas/process-document/33b772ef206c23ff.zip`.

## Live verification

AWS API checks and real asynchronous S3 events confirmed:

- the Lambda is active on Python 3.12, arm64, 512 MB, with a 60-second timeout;
- the EventBridge rule is enabled and filters the exact bucket plus `uploads/`;
- the target points to the processing Lambda with two retries and a one-hour
  maximum event age;
- a generated two-page PDF produced `EXTRACTED` status, page count 2, character
  count 87, and the correct page-numbered text;
- a fake PDF produced `FAILED` status with `INVALID_PDF_SIGNATURE`;
- CloudWatch recorded structured `document_extracted` and `document_rejected`
  events; and
- the deployed IAM policies match the two S3 prefix permissions above.

All generated upload, extraction, and status objects were removed after the
test, leaving the document bucket empty. Account identifiers and credentials
are intentionally excluded from this record.

## Automated tests

Sixteen unit tests pass: nine upload-handler tests and seven processor tests.
Processor coverage includes event filtering, page-aware extraction from a real
generated PDF, malformed PDF rejection, metadata validation, no-text rejection,
configured limits, status writes, and retry behavior for transient failures.
