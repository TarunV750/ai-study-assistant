# Phase 10: Grounded RAG Question Answering

Phase 10 composes semantic retrieval with Amazon Bedrock generation. The
`ask-question` Lambda retrieves relevant chunks, constructs a bounded prompt,
invokes Amazon Nova Micro through the Bedrock Converse API, and returns an
answer plus source metadata.

Nova Micro was selected as the configurable development default because the
application is text-only and benefits from its low latency and cost. The model
ID remains a CloudFormation parameter so a larger model can be substituted
without source changes.

## Grounding controls

- System instructions and the user message are separate Converse fields.
- Retrieved chunks are delimited and numbered as source data.
- The system prompt labels uploaded material as untrusted and says to ignore
  commands found inside it.
- The model is instructed to use no outside knowledge and cite `[Source N]`.
- Context and output token counts are bounded.
- When retrieval returns no qualifying chunks, the Lambda skips generation and
  returns an explicit insufficient-material response.
- Logs contain request IDs, source counts, and token usage, not questions or
  document text.

This prompt-level isolation reduces prompt-injection risk but does not eliminate
it. Phase 15 documents production controls such as authentication, Bedrock
Guardrails, monitoring, and adversarial evaluation.

## Reference

- [Using the Converse API with Amazon Nova](https://docs.aws.amazon.com/nova/latest/userguide/using-converse-api.html)
