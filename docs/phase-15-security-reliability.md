# Phase 15: security and reliability hardening

This phase hardens every public path without exposing implementation details to clients.

## Controls implemented

- S3 remains private, encrypted, and reachable for upload only through a five-minute presigned form constrained to PDF content and a server-defined size limit.
- Lambda roles are separated by responsibility. Bedrock and OpenSearch permissions are limited to the configured models, collection, and index.
- API Gateway allows one exact frontend origin, only required methods/headers, and applies stage throttling.
- POST handlers require JSON in real HTTP requests, reject base64 and bodies larger than 8 KiB, and validate field lengths, types, identifiers, and enum values.
- API responses disable caching and MIME sniffing. Exceptions are logged by type but internal service details are not returned.
- Logs are structured JSON and avoid document text, questions, model responses, credentials, presigned fields, and AWS account identifiers.
- Uploaded PDF text is untrusted prompt data. System instructions prohibit following instructions inside sources, and answers must contain valid source markers.
- CloudWatch records API access logs and detailed metrics. Alarms watch API 5xx responses and combined RAG Lambda errors.

## Trust boundary and production note

The current `dev` API is a single-user portfolio sandbox. It has exact CORS and throttling but no user authentication; CORS is a browser control, not authorization. Do not expose this deployment as a multi-user production service. A production phase should add a Cognito/JWT authorizer, per-user S3 prefixes and vector filters, quotas, alarm notifications, and deletion/retention workflows. Document deletion is deliberately not exposed on the anonymous API.

## Failure behavior

Validation failures return 400 with a safe field-specific message. Missing documents return 404. Configuration failures return 500 without secrets. Temporary S3, Bedrock, or OpenSearch failures return 502. Event-driven processing failures are recorded in each document's status object and remain observable in CloudWatch.
