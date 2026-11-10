# Phase 14: citations and no-answer behavior

Every newly indexed chunk now carries the original PDF filename along with its document, page, and chunk identifiers. Retrieval returns that provenance, so the API and React interface can display human-readable filename and page citations.

Because filename provenance adds a field to an index that may already exist, the indexing role has narrowly scoped `aoss:UpdateIndex` permission for that one index. This permits OpenSearch to extend the mapping without granting collection administration.

The answer path has two independent grounding checks:

1. Retrieval returns no context when no passage reaches the configurable relevance threshold. The API then returns a deterministic no-answer message without calling a generation model.
2. When Bedrock generates an answer or study resource, the API parses `[Source N]` markers, rejects output with no valid citation, and returns only the cited source metadata. A model-produced exact no-answer response is returned with an empty source list.

Uploaded source text is delimited and explicitly treated as untrusted data in the system instruction, reducing the risk that instructions embedded in a PDF override application behavior.
