# Phase 3 Development Deployment

- **Date:** 2026-09-26
- **Region:** `us-east-1`
- **Artifact stack:** `ai-study-assistant-dev-artifacts` — `CREATE_COMPLETE`
- **Foundation stack:** `ai-study-assistant-dev-foundation` — `UPDATE_COMPLETE`
- **Templates:** `infrastructure/artifacts.yaml` and
  `infrastructure/foundation.yaml`
- **Template validation:** local `cfn-lint` and AWS CloudFormation validation
  passed

## Reviewed changes

The foundation change set contained three additions, one in-place modification,
and no replacements or deletions:

- added one private `AWS::S3::Bucket` for documents;
- added its `AWS::S3::BucketPolicy`;
- added the `AWS::Lambda::Function` that signs uploads; and
- modified only `CreateUploadUrlRole` to allow `s3:PutObject` on the document
  bucket's `uploads/*` prefix.

The separate artifact stack added one private S3 bucket and its TLS-only bucket
policy. Lambda code was uploaded under the content-derived key
`lambdas/create-upload-url/7ccee24152f9ecaa.zip`.

## Deployment note

The first foundation update rolled back because reserving five concurrent Lambda
executions would have reduced the account's unreserved pool below AWS's required
minimum of ten. The template was corrected to leave concurrency unreserved,
revalidated, reviewed as a new change set, and deployed successfully. API-level
throttling will be introduced when API Gateway exposes the Lambda.

## Live verification

AWS API checks and a real upload confirmed:

- the Lambda is active on Python 3.12, arm64, 128 MB, and a 10-second timeout;
- a valid request returned a 300-second presigned POST;
- a real 23,248-byte PDF uploaded directly to S3 with HTTP 204;
- S3 recorded `application/pdf`, `AES256`, and all signed metadata;
- invalid `.txt` input returned a structured HTTP 400 response;
- an unauthenticated object GET returned HTTP 403;
- all four S3 public-access-block controls are enabled;
- S3 reports the bucket policy as non-public;
- CORS allows only `POST` from `http://localhost:5173`;
- the Lambda role's application permission is exactly `s3:PutObject` on
  `uploads/*`; and
- CloudWatch contains structured success and validation-rejection events.

The generated test object was deleted after verification, leaving no test upload
in the document bucket. Account identifiers and credentials are intentionally
excluded from this record.

## Automated tests

Nine unit tests pass for valid signing, direct invocation, malformed JSON,
filename and path rejection, MIME rejection, size bounds, session ID validation,
and S3 signing failure handling.
