# Infrastructure

AWS CloudFormation keeps the development environment repeatable and reviewable.
The deployed development environment uses two stacks:

- `artifacts.yaml` creates a private bucket for versioned Lambda ZIP files.
- `foundation.yaml` creates the application roles, log groups, private document
  bucket, upload Lambda, PDF extraction/chunking Lambda, and Bedrock embedding
  Lambda, plus the OpenSearch Serverless vector collection and policies.

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
   structure before extracting and chunking text.
4. Successful extraction writes page-aware text to
   `processing/<document-id>/extracted.json` and configurable overlapping text
   to `chunks.json`, then writes `status.json` last as the completion marker.
5. A permanently invalid document gets a structured `FAILED` status. Transient
   AWS errors are retried by EventBridge.

The processing role can read only `uploads/*` and write only `processing/*`.
Scanned image-only and password-protected PDFs are rejected; OCR is outside the
current pipeline.

## Embedding flow

1. S3 publishes creation of `processing/<document-id>/chunks.json`.
2. A suffix-filtered EventBridge rule invokes `generate-embeddings`.
3. The Lambda validates the artifact and its deterministic chunk contract.
4. Each chunk is sent to the configured Amazon Bedrock embedding model.
5. The Lambda validates vector dimensions and finite values, then writes
   `embeddings.json` and a final `EMBEDDED` status.

The default is Amazon Titan Text Embeddings V2 with normalized 1,024-dimension
vectors. The dedicated role can read only chunk and completion-status artifacts,
write only embedding and status artifacts, and invoke only that configured
foundation model.

## Vector-search foundation

Phase 7 provisions a `VECTORSEARCH` collection, but intentionally does not
create an index or write documents yet. Those are Phase 8 responsibilities.

The collection uses:

- a `NEXTGEN` collection group with indexing and search minimums of zero and
  maximums of two OCUs each;
- the next-generation group's required high-availability behavior and standard
  vector-index path;
- encryption with an AWS-owned key;
- a publicly reachable API endpoint that still requires signed, authorized
  requests; and
- a data-access policy naming only the embedding role.

The embedding role does not yet have `aoss:APIAccessAll`, so the Phase 7 policy
does not grant it effective data-plane access on its own. Phase 8 will add only
the IAM permission needed to create the index and write vectors.

## Validate and test

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r infrastructure/requirements-dev.txt
make backend-test
make infra-validate AWS_PROFILE=YOUR_PROFILE AWS_REGION=us-east-1
```

`backend-test` tests upload signing, PDF processing, chunking, and embedding
behavior without contacting AWS.
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
2. packages the upload, processing, and embedding Lambdas, including the pinned
   `pypdf` runtime dependency;
3. uploads them under source-content hashes; and
4. updates the foundation stack with all three artifact locations.

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
aws s3 cp s3://DOCUMENTS_BUCKET/processing/DOCUMENT_ID/chunks.json - \
  --profile YOUR_PROFILE --region us-east-1
aws s3 cp s3://DOCUMENTS_BUCKET/processing/DOCUMENT_ID/embeddings.json - \
  --profile YOUR_PROFILE --region us-east-1
```

An `EMBEDDED` status includes the model, dimensions, and chunk count. A `FAILED`
status contains a stable error code, safe message, and failed stage. Chunk and
embedding settings are CloudFormation parameters.

## Costs and cleanup

S3 charges for storage and requests; Lambda, EventBridge, and Amazon Bedrock may
charge for processing; CloudWatch Logs charges for ingested and retained data.
OpenSearch Serverless charges for active OCUs and stored data. Its configured
minimum is zero while idle, but tests, indexing, and searches can activate paid
capacity. Costs are not guaranteed to be zero. Artifact objects expire after 30
days, and logs retain for 14 days. Uploaded documents and extracted text do not
automatically expire.

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
