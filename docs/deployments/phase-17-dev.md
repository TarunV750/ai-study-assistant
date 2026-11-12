# Phase 17 development deployment and end-to-end verification

Verified on November 11, 2026 in the existing `dev` stack in `us-east-1`.
Account IDs, endpoints, bucket names, document IDs, and credentials are omitted.

## Deployment state

- Foundation stack: `UPDATE_COMPLETE`
- CloudFormation drift: `IN_SYNC` with zero drifted resources
- Question and study Lambdas: active and successfully invoked through API Gateway
- Indexed verification PDF: 23 chunks with filename/page provenance

## Automated verification

- Python backend and infrastructure-contract tests: 82 passing
- React/Vitest tests: 4 passing
- React production build: passing
- CloudFormation lint: passing
- AWS template validation: passing

## Live smoke test

The reusable `scripts/e2e_smoke.py` test passed these checks against the deployed
API and an already indexed lecture PDF:

1. document listing;
2. single-document status;
3. `no-store`/`nosniff` response behavior;
4. exact-origin CORS preflight;
5. constrained five-minute presigned upload instructions;
6. a grounded answer with filename/page citations; and
7. a grounded Study Guide with citations.

The upload smoke check creates instructions but does not upload another object,
so repeated verification is non-destructive apart from normal API/model usage.

## Drift correction

The first drift scan found two API Gateway normalizations: lowercase
`content-type` and removal of the log-group ARN wildcard suffix. The template was
updated to represent those service-normalized values, deployed in place with no
resource replacements, and the second scan returned `IN_SYNC`.

## Run again

```bash
API_ENDPOINT=https://... \
DOCUMENT_ID=... \
SMOKE_QUESTION="A question known to be answered by that document" \
FRONTEND_ORIGIN=http://localhost:5173 \
make e2e-smoke
```
