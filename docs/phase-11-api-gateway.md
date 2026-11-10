# Phase 11: API Gateway HTTP Endpoints

Phase 11 adds an Amazon API Gateway HTTP API with Lambda proxy integrations and
payload format 2.0. HTTP API was selected over the older API Gateway REST API
product because these routes need straightforward JSON/Lambda proxy behavior,
and HTTP API has less configuration and lower request cost while remaining a
RESTful HTTPS interface.

## Routes

| Method | Path | Lambda | Purpose |
|---|---|---|---|
| `POST` | `/upload-url` | `create-upload-url` | Validate PDF metadata and return a presigned S3 POST |
| `POST` | `/ask` | `ask-question` | Retrieve chunks and generate a grounded answer |
| `GET` | `/documents` | `manage-documents` | List up to 100 processing records |
| `GET` | `/documents/{documentId}` | `manage-documents` | Read one document's current status |

The document API reads only status objects and upload metadata. It does not
return S3 keys, extracted text, vectors, or credentials.

## API controls

- CORS allows only the configured frontend origin, `Content-Type`, and the
  required methods.
- The default stage auto-deploys reviewed CloudFormation changes.
- Per-stage throttling is 10 requests/second with a burst of 20.
- Structured access logs record request ID, route, status, response length, and
  integration error—not request bodies.
- Lambda invocation permissions name the API, method, and route.
- Lambda responses disable caching and use stable JSON error shapes.

The development API is intentionally unauthenticated at this phase so the local
React client can exercise it. Phase 15 records this single-user development
boundary and the Cognito/JWT requirement before any multi-user deployment.

## References

- [HTTP API Lambda proxy integrations](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-develop-integrations-lambda.html)
- [HTTP API CORS configuration](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-properties-apigatewayv2-api-cors.html)
