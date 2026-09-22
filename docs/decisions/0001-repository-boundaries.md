# ADR 0001: Separate UI, handlers, shared logic, and infrastructure

- **Status:** Accepted
- **Date:** 2026-09-22

## Context

The application includes a browser client, multiple event/API Lambda handlers,
reusable RAG logic, and deployable AWS configuration. Mixing these concerns
would make testing and deployments harder to reason about.

## Decision

Use top-level `frontend`, `backend`, `infrastructure`, and `docs` directories.
Within the backend, give each Lambda a package and put reusable code in
`shared`. Keep tests next to the backend boundary they exercise.

## Consequences

Handlers can be packaged independently, shared logic can be unit tested without
invoking Lambda, and infrastructure changes remain reviewable separately. The
build process will need to package shared code with each function or publish it
as a Lambda layer; that choice is deferred until the infrastructure phase.
