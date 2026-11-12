# Phase 16: expanded automated testing

Phase 16 closes two gaps in the earlier test strategy.

- React tests exercise PDF validation, document selection, study-tool enablement, question submission, and citation rendering in a browser-like DOM.
- Infrastructure contract tests protect security-critical CloudFormation behavior: required routes, exact-origin CORS, private S3 controls, TLS enforcement, API throttling, access logs, alarms, and separation of vector read/write principals.

The existing backend suite continues to cover validation boundaries, event idempotency, document processing, embeddings, indexing, retrieval, grounded generation, citations, safe errors, and study tools. All tests remain offline and use fakes or mocks; live AWS behavior is verified separately in Phase 17.

Run the complete local suite with:

```bash
make test
make infra-lint
cd frontend && npm run build
```
