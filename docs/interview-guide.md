# CourseLens AI interview guide

Use this as a speaking guide, not a script to memorize word for word.

## 30-second explanation

> I built CourseLens AI, an event-driven study assistant on AWS. A student
> uploads a course PDF directly to private S3, Lambda extracts and chunks the
> text, Bedrock creates embeddings, and OpenSearch Serverless indexes them. For
> a question, the API embeds the query, retrieves relevant page-aware chunks,
> and asks Amazon Nova to answer only from those sources. The response includes
> filename and page citations, and the API refuses weak or uncited answers. I
> deployed the system with CloudFormation and verified it with backend,
> frontend, infrastructure-contract, drift, and live end-to-end tests.

## Two-minute walkthrough

1. **Problem:** Generic AI can answer fluently without using a student's actual
   lecture material. I wanted a verifiable evidence boundary.
2. **Upload:** The React client requests a five-minute presigned POST and uploads
   directly to private S3. This avoids passing PDF bytes through Lambda.
3. **Ingestion:** S3 events flow through EventBridge to separate extraction,
   embedding, and indexing Lambdas. Each validates the previous stage's artifact
   and writes its completion status last.
4. **Retrieval:** Titan Text Embeddings V2 creates normalized 1,024-dimension
   vectors. OpenSearch Serverless performs filtered semantic retrieval using
   document IDs selected by the student.
5. **Generation:** Nova Micro receives delimited source passages. It must cite
   `[Source N]`; the backend validates citations and returns filename/page
   metadata. No relevant chunks means a deterministic no-answer without a model
   generation call.
6. **Study tools:** Summaries and guides use a broader top-10 retrieval policy,
   but only across explicitly selected documents. Narrow questions retain a
   stricter relevance threshold.
7. **Engineering quality:** Per-function IAM roles, exact data policies, input
   limits, structured logs, alarms, CloudFormation, 86 local tests, a live smoke
   test, and zero-drift verification make behavior reproducible and reviewable.

## Whiteboard architecture

Draw two paths.

```text
INGESTION
React ──presigned POST──> private S3
                            │ Object Created
                            ▼
                      EventBridge
                            │
             Extract/Chunk → Embed → Index
                              │        │
                           Bedrock   OpenSearch

QUERY
React → API Gateway → Ask/Study Lambda
                         │       │
                    embed query  retrieve chunks
                         └──> OpenSearch
                                 │
                          grounded prompt
                                 │
                           Bedrock Nova
                                 │
                       answer + page citations
```

Then explain the trust boundaries: the browser has no AWS credentials; S3 and
OpenSearch are private-by-authorization; Lambda roles are separated; PDF text is
untrusted prompt data; and citation validation happens after generation.

## Design questions and strong answers

### Why use presigned uploads?

They keep large PDF bytes off the API/Lambda path. The backend still controls the
key, MIME type, maximum size, encryption header, metadata, and five-minute
expiry. Browser validation improves feedback, but the signed policy and
processor validation are the security boundary.

### Why separate Lambdas instead of one large function?

Extraction, embedding, and indexing have different failure modes, permissions,
and scaling behavior. Separate stages make retries targeted, roles smaller, logs
clearer, and each artifact contract independently testable. The cost is more
orchestration and eventual consistency.

### How do you prevent hallucinations?

I cannot guarantee a generative model never hallucinates. I reduce the risk with
filtered retrieval, a relevance threshold, a prompt that forbids outside
knowledge, delimited untrusted sources, low temperature, deterministic no-answer
behavior, and post-generation citation validation. The UI exposes the source
filename/page so the student can verify the result.

### Why are Q&A and Study Guide thresholds different?

A question has a narrow semantic target, so a relevance floor protects against
answering from weak matches. “Create a study guide” is deliberately broad; its
embedding can score below that threshold even for a valid selected PDF. Study
tools therefore require explicit document selection and take the top 10 passages
with a separate floor. That decision came from a real live-test failure.

### How is retry safety handled?

EventBridge provides at-least-once delivery. Chunk IDs and OpenSearch document
IDs are deterministic, and the index operation overwrites the same logical
record. Each stage validates the expected status/artifact pair before work and
writes the completion marker last.

### What would you change for production?

Add Cognito/JWT authentication, tenant IDs and authorization filters throughout
S3/OpenSearch, deletion and retention workflows, SQS dead-letter queues, alarm
notifications, WAF/per-user quotas, DynamoDB document metadata, bounded parallel
embedding calls, OCR, a hosted frontend, and measured cost/latency dashboards.

## STAR debugging stories

### OpenSearch indexing authorization

- **Situation:** A real 23-chunk PDF stayed at “Indexing,” although embeddings
  completed.
- **Task:** Find the final-stage failure without logging document content.
- **Action:** I enhanced bulk-response diagnostics to expose only OpenSearch
  error type/reason, replayed the idempotent event, and found an authorization
  exception. Filename provenance was extending an existing mapping, which
  required `aoss:UpdateIndex`. I added that permission only to the exact index.
- **Result:** The same document indexed successfully, changed to Ready, and
  produced cited answers. A regression test now preserves safe diagnostics.

### Study Guide false no-answer

- **Situation:** Q&A worked, but Study Guide reported no relevant material.
- **Task:** Preserve no-answer safety without rejecting broad study requests.
- **Action:** I compared live scores and found the broad prompt reused the narrow
  Q&A threshold. I required explicit selection and created a top-10 study policy
  while keeping Q&A strict.
- **Result:** The guide generated from six cited lecture pages, and frontend and
  handler tests protect the selection/retrieval behavior.

## Tradeoffs to volunteer

- Character-based chunks are simple and page-traceable, but token-aware semantic
  chunking could improve retrieval.
- OpenSearch Serverless reduces operations work and can scale to zero, but has
  service-specific authorization and less predictable cold-start latency.
- S3 status objects avoid another database in a portfolio system, but document
  listing becomes inefficient at scale.
- Nova Micro controls generation cost and latency, but a larger model might
  improve synthesis; evaluation should drive that decision.
- The development API is intentionally unauthenticated, so it is not suitable as
  a public multi-user deployment.

## Resume bullets

- Built and deployed an event-driven AWS RAG application using React, API
  Gateway, Lambda, S3, EventBridge, Bedrock, OpenSearch Serverless, CloudWatch,
  IAM, and CloudFormation.
- Implemented page-aware PDF ingestion, normalized 1,024-dimension embeddings,
  filtered semantic retrieval, grounded generation, filename/page citations,
  and deterministic no-answer behavior.
- Created 82 backend/infrastructure and 4 frontend tests plus a seven-check live
  AWS smoke test and CloudFormation drift verification.
- Diagnosed and fixed OpenSearch data-policy/mapping authorization and retrieval
  threshold bugs discovered during real end-to-end testing.

## Questions to ask the interviewer

- How does your team evaluate retrieval quality separately from generation
  quality?
- What production signals determine whether you change chunking, reranking, or
  the generation model?
- How do you isolate tenant data in shared vector-search infrastructure?
- What is your approach to cost attribution and quality regression testing for
  generative AI features?
