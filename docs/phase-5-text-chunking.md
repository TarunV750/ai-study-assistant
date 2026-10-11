# Phase 5: Configurable Overlapping Text Chunking

Phase 5 converts extracted page text into retrieval-sized units for the later
embedding and semantic-search stages.

## Why chunk text

Embedding an entire course PDF as one value would lose local detail and exceed
model input limits. Very small chunks lose context. Overlapping chunks balance
those concerns: each chunk stays bounded while adjacent chunks repeat some text
so an idea near a boundary is not split without context.

## Strategy

The chunker uses these development defaults:

- maximum chunk size: 1,200 characters;
- overlap: 200 characters;
- maximum chunks per document: 5,000;
- page boundaries: always preserved.

It prefers a whitespace boundary within the final 40% of the target window and
starts subsequent chunks at a word boundary when possible. Therefore, the
effective overlap can differ slightly from the configured 200-character target.
It uses a hard character boundary only for long unbroken text. Empty pages are
skipped. Configuration validation requires a positive size and limit, a
non-negative overlap, and overlap smaller than chunk size.

Character-based chunking is transparent, deterministic, model-independent, and
easy to test. Token-aware chunking may be evaluated after the Bedrock embedding
model is selected because tokenization depends on the chosen model.

## Output contract

The processor retains Phase 4's `extracted.json` and adds:

```text
processing/<document-id>/chunks.json
```

Each chunk contains:

- a deterministic ID and zero-based global index;
- its PDF page and zero-based index within that page;
- start and end character offsets into the extracted page text;
- character count and exact chunk text.

`chunks.json` also records the applied strategy and its settings. After writing
both extraction and chunk outputs, the processor writes a final `CHUNKED`
status with all three counts. If the document exceeds the configured chunk
limit, it writes `FAILED` with `TOO_MANY_CHUNKS` and does not leave partial
extraction or chunk outputs.

## Retrieval implications

Preserving page boundaries makes every future search result directly citable to
one source page. Overlap improves contextual continuity but means adjacent
results can contain repeated text; the later retrieval stage should deduplicate
or diversify results before prompt construction.
