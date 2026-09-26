# Phase 3: Secure direct PDF uploads

## Goal

Let a browser upload a PDF to private S3 storage without receiving AWS
credentials or sending the file through Lambda.

## Design

The client sends only metadata to `create-upload-url`. After validation, Lambda
returns a short-lived S3 presigned POST containing signed form fields. The file
then travels directly from the client to S3.

This pattern keeps credentials on AWS, avoids Lambda payload limits, and avoids
paying Lambda to relay file bytes. A UUID-based object key prevents user-supplied
filenames from becoming S3 paths. The original filename is percent-encoded and
stored only as metadata.

## Enforced controls

- filename ends in `.pdf` and contains no path or control characters;
- content type is exactly `application/pdf`;
- declared and uploaded size is between 1 byte and 10 MiB;
- upload form expires after five minutes;
- each upload receives a unique `uploads/<uuid>/document.pdf` key;
- S3 requires signed metadata and `AES256` server-side encryption;
- bucket public access is blocked and insecure transport is denied;
- Lambda IAM access is limited to `s3:PutObject` on `uploads/*`.

## Boundary of this phase

This phase creates the backend upload primitive, but does not expose it through
API Gateway or a frontend. It also does not trust the resulting object as a PDF.
Phase 4 will respond to new objects, parse the bytes, enforce page/text limits,
and quarantine or delete invalid content before downstream AI processing.

The optional `sessionId` is trace metadata, not authentication or authorization.
Real user identity will replace it when authentication is introduced.
API Gateway authentication and request throttling will be added when this
Lambda is exposed as a public endpoint. Function-level reserved concurrency is
not used because the development account's concurrency quota must retain AWS's
minimum unreserved pool.
