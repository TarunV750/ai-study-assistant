# Phase 19: complexity, security, cost, and bug review

This review distinguishes development-sandbox controls from production
requirements. “Accepted” means appropriate for the current single-user portfolio
environment, not universally safe.

## Complexity and scaling

| Path | Current behavior | Scaling implication | Next evolution |
| --- | --- | --- | --- |
| PDF extraction | Linear in PDF bytes, pages, and extracted characters | Bounded by 10 MiB, 200 pages, and 2M characters | Step Functions or container work for larger/OCR documents |
| Chunking | Linear in characters; overlap increases stored text | Bounded by 5,000 chunks, embedding stage currently caps at 500 | Token-aware chunking and batched/concurrent embeddings |
| Embeddings | One Bedrock request per chunk | Network latency grows linearly with chunk count | Bounded concurrency with retry/backoff and service quotas |
| Indexing | Linear in chunks × 1,024 vector dimensions | Bulk batches cap request size; deterministic IDs keep retry safe | Tune batch size from CloudWatch latency/error evidence |
| Retrieval | Managed approximate vector search, top-k at most 10 | Prompt work stays bounded as corpus grows | Hybrid lexical/vector retrieval and reranking |
| Document list | Up to 100 documents, with S3 reads per status/filename | Appropriate for a demo; inefficient for many users/documents | DynamoDB metadata index with pagination |

## Security review

| Finding | Severity | Status / control |
| --- | --- | --- |
| Development HTTP API has no authentication | High before public production | Accepted only for a private sandbox; add Cognito/JWT and tenant authorization |
| Browser never receives AWS credentials | High | Controlled with short-lived constrained presigned POSTs |
| Public OpenSearch network endpoint | High | SigV4 plus IAM and exact-principal data policies; no anonymous data access |
| Prompt injection through uploaded PDFs | High | Source text is delimited/untrusted; outside knowledge forbidden; citations validated |
| Cross-origin browser calls | Medium | Exact configured origin and minimal methods/headers; CORS is not treated as auth |
| Resource abuse and model spend | Medium | API throttling, input limits, top-k/context/token caps, model-scoped IAM |
| Sensitive content in logs | Medium | Structured metadata only; prompts, PDF text, responses, credentials, and form fields omitted |
| Failed async events after retry exhaustion | Medium | CloudWatch-visible today; add SQS dead-letter queues and alarm notification targets |
| User-controlled Markdown links/HTML | Medium | React Markdown allows only safe structural elements; links, images, and raw HTML are excluded |

## Cost review

Primary variable costs are Bedrock embedding/generation tokens, OpenSearch active
capacity and storage, Lambda duration, S3 requests/storage, and CloudWatch logs.
The current design controls them through:

- direct S3 upload rather than Lambda byte transfer;
- 10 MiB/200-page/500-embedded-chunk ceilings;
- 1,024-dimension normalized vectors and bounded bulk indexing;
- query top-k of 5 and study top-k of 10;
- 12,000-character context, 700 answer-token, and 1,400 study-token limits;
- a NextGen vector collection group with zero minimum and two-OCU maximums;
- 14-day log retention and 30-day deployment-artifact expiry;
- API throttling and CloudWatch error alarms.

No fixed monthly-cost claim is made because AWS pricing and usage vary. Before a
public launch, add AWS Budgets, anomaly alerts, authenticated per-user quotas,
document retention rules selected by the owner, and measured cost-per-document /
cost-per-question dashboards.

## Bugs found and disposition

| Bug | Root cause | Resolution |
| --- | --- | --- |
| Frontend upload failed against live API contract | Client used `fileName` and ignored nested `upload` fields | Matched the backend contract and added browser validation tests |
| Ready documents stayed disabled | UI compared lowercase states to uppercase backend states | Normalized processing status once at the UI boundary |
| Real PDF remained at Indexing | Filename provenance extended an existing mapping without `aoss:UpdateIndex` | Added exact-index permission and safe bulk-error diagnostics |
| Study Guide returned no relevant material | Broad query reused narrow Q&A score threshold | Required selected documents and introduced top-10 study retrieval |
| Study model speculated from a one-line source | Prompt allowed elaboration despite sparse evidence | Explicit no-speculation instruction plus citation enforcement |
| Model Markdown displayed as raw punctuation | Output was rendered as plain text | Added allowlisted, HTML-free Markdown rendering |
| Stack reported two drifted resources | API Gateway normalized header case and log-group ARN | Template now describes the normalized deployed values |

## Accepted limitations

- Text-based PDFs only; no OCR or password-protected files.
- No multi-user identity, deletion API, retention UI, or hosted frontend yet.
- Retrieval uses semantic vector search without lexical hybrid search or reranking.
- Study material represents the retrieved top passages, not a guaranteed exhaustive
  summary of every page.
