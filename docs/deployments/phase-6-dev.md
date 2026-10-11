# Phase 6 Development Deployment

- **Date:** 2026-10-10 local time / 2026-10-11 UTC
- **Region:** `us-east-1`
- **Foundation stack:** `ai-study-assistant-dev-foundation` — `UPDATE_COMPLETE`
- **Embedding function:** `ai-study-assistant-dev-generate-embeddings` — `Active`
- **Model:** `amazon.titan-embed-text-v2:0`
- **Template validation:** local `cfn-lint` and AWS CloudFormation validation
  passed

## Model-access verification

The Bedrock model catalog reported Titan Text Embeddings V2 as active with
on-demand inference in `us-east-1`. A direct invocation returned a
1,024-dimensional vector and an input-token count before deployment.

## Reviewed changes

The change set contained five additions and no modifications, replacements, or
deletions:

- embedding Lambda;
- dedicated least-privilege IAM role;
- 14-day CloudWatch log group;
- suffix-filtered EventBridge rule; and
- EventBridge Lambda invocation permission.

After adding and testing the chunk-completion readiness guard, the final
content-derived artifact key was
`lambdas/generate-embeddings/5c640634fd5f9455.zip`. The guard update modified
the new Lambda and its dedicated role in place; it did not replace data
resources.

## Live end-to-end verification

A real two-page PDF traveled through S3 upload, PDF extraction, chunking, and
embedding without direct Lambda invocation. The final result confirmed:

- final status `EMBEDDED`;
- two chunks and two vectors;
- model ID `amazon.titan-embed-text-v2:0`;
- exactly 1,024 finite values in each vector;
- vector L2 norm `1.0` for both normalized vectors;
- deterministic chunk IDs and correct page numbers;
- input-token count 8 for each test chunk; and
- a structured CloudWatch `document_embedded` event with matching metadata.

The deployed function uses Python 3.12, arm64, 512 MB, and a 300-second timeout.
The EventBridge rule is enabled, filters `/chunks.json`, and retries twice within
one hour. Live IAM inspection confirmed the exact S3 object patterns and single
foundation-model ARN described in the design document.

The generated upload and all processing artifacts were removed after testing,
leaving the document bucket empty. Account identifiers and credentials are
intentionally excluded.

## Automated tests

Thirty-three unit tests pass. The eight Phase 6 tests cover successful multi-chunk
embedding, model request configuration, event filtering, schema rejection,
chunk-limit enforcement, invalid JSON, retry behavior, and malformed-vector
rejection, including retry behavior when chunking status is not ready.
