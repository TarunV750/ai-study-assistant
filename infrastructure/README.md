# Infrastructure

AWS CloudFormation keeps the development environment repeatable and reviewable.
The deployed development environment uses two stacks:

- `artifacts.yaml` creates a private bucket for versioned Lambda ZIP files.
- `foundation.yaml` creates the application roles, log groups, private document
  bucket, upload Lambda, and event-driven PDF extraction Lambda.

## Secure upload flow

1. A client asks `create-upload-url` to upload a named PDF of a declared size.
2. The Lambda rejects invalid names, MIME types, sizes, and session IDs.
3. It creates a random document ID and a five-minute S3 presigned POST.
4. The browser sends the file directly to the private document bucket.
5. S3 accepts only the signed key, metadata, `application/pdf`, SSE-S3 header,
   and a body within the configured size range.

The Lambda role can only put objects below `uploads/`; it cannot list or read
documents. The bucket blocks public access, enforces TLS and encryption headers,
and allows browser POSTs only from the configured frontend origin. CORS controls
browser behavior; IAM and the signed POST policy provide authorization.

## PDF extraction flow

1. S3 sends an Object Created event to Amazon EventBridge.
2. An EventBridge rule accepts only keys under `uploads/` in this bucket.
3. The processing Lambda validates the key, metadata, size, MIME type, and PDF
   structure before extracting text.
4. Successful extraction writes page-aware text to
   `processing/<document-id>/extracted.json`, then writes `status.json` last as
   the completion marker.
5. A permanently invalid document gets a structured `FAILED` status. Transient
   AWS errors are retried by EventBridge.

The processing role can read only `uploads/*` and write only `processing/*`.
Scanned image-only and password-protected PDFs are rejected in this phase; OCR
and chunking are separate later phases.

## Validate and test

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r infrastructure/requirements-dev.txt
make backend-test
make infra-validate AWS_PROFILE=YOUR_PROFILE AWS_REGION=us-east-1
```

`backend-test` tests upload signing and PDF processing without contacting AWS.
`infra-validate` performs local syntax/lint checks and AWS template validation.

## Deploy

First confirm the intended AWS identity:

```bash
aws sts get-caller-identity --profile YOUR_PROFILE --region us-east-1
```

Then package, upload, and deploy:

```bash
make infra-deploy AWS_PROFILE=YOUR_PROFILE AWS_REGION=us-east-1
```

The Make target:

1. deploys the private artifact bucket;
2. packages the upload and processing Lambdas, including the pinned `pypdf`
   runtime dependency;
3. uploads them under source-content hashes; and
4. updates the foundation stack with both artifact locations.

For a production workflow, create and inspect a CloudFormation change set before
execution. If an organization requires an IAM permissions boundary, pass
`PermissionsBoundaryArn` when deploying the foundation stack.

## Verify

```bash
make infra-describe AWS_PROFILE=YOUR_PROFILE AWS_REGION=us-east-1
aws s3api get-public-access-block --bucket DOCUMENTS_BUCKET \
  --profile YOUR_PROFILE --region us-east-1
aws s3api get-bucket-encryption --bucket DOCUMENTS_BUCKET \
  --profile YOUR_PROFILE --region us-east-1
```

Invoke the Lambda with an API-style body, then submit every returned form field
plus the file to `upload.url`. A successful S3 form upload returns HTTP 204.
`head-object` should show `application/pdf`, `AES256`, and the signed metadata.
The upload then triggers extraction asynchronously. Verify the result with:

```bash
aws s3 cp s3://DOCUMENTS_BUCKET/processing/DOCUMENT_ID/status.json - \
  --profile YOUR_PROFILE --region us-east-1
aws s3 cp s3://DOCUMENTS_BUCKET/processing/DOCUMENT_ID/extracted.json - \
  --profile YOUR_PROFILE --region us-east-1
```

An `EXTRACTED` status includes the page and character counts. A `FAILED` status
contains a stable error code and safe message.

## Costs and cleanup

S3 charges for storage and requests; Lambda and EventBridge may charge for
processing; CloudWatch Logs charges for ingested and retained log data. At
portfolio-testing volume these should be small, but they are not guaranteed to
be zero. Artifact objects expire after 30 days, and logs retain for 14 days.
Uploaded documents and extracted text do not automatically expire.

Empty the document bucket before deleting the foundation stack. Then remove the
artifact stack:

```bash
aws s3 rm s3://DOCUMENTS_BUCKET --recursive \
  --profile YOUR_PROFILE --region us-east-1
make infra-delete AWS_PROFILE=YOUR_PROFILE AWS_REGION=us-east-1
make artifacts-delete AWS_PROFILE=YOUR_PROFILE AWS_REGION=us-east-1
```

These commands permanently delete uploaded documents and deployment artifacts;
review the bucket names before running them.
