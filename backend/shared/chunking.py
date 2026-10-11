"""Deterministic, page-aware character chunking for extracted document text."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class ChunkingConfigurationError(ValueError):
    """The configured chunking limits cannot produce valid chunks."""


class ChunkLimitExceeded(ValueError):
    """A document would produce more chunks than the processing limit."""


@dataclass(frozen=True)
class ChunkingConfig:
    max_characters: int
    overlap_characters: int
    max_chunks: int

    def validate(self) -> None:
        if self.max_characters < 1:
            raise ChunkingConfigurationError("Chunk size must be positive.")
        if self.overlap_characters < 0:
            raise ChunkingConfigurationError("Chunk overlap cannot be negative.")
        if self.overlap_characters >= self.max_characters:
            raise ChunkingConfigurationError(
                "Chunk overlap must be smaller than the chunk size."
            )
        if self.max_chunks < 1:
            raise ChunkingConfigurationError("Maximum chunk count must be positive.")


def _preferred_end(text: str, start: int, max_characters: int) -> int:
    """Choose a readable boundary without creating very short chunks."""
    hard_end = min(start + max_characters, len(text))
    if hard_end == len(text):
        return hard_end

    earliest_boundary = start + max(1, (max_characters * 3) // 5)
    for index in range(hard_end, earliest_boundary - 1, -1):
        if text[index - 1].isspace():
            return index
    return hard_end


def chunk_pages(
    pages: list[dict[str, Any]],
    *,
    document_id: str,
    config: ChunkingConfig,
) -> list[dict[str, Any]]:
    """Split text into overlapping chunks without crossing PDF page boundaries."""
    config.validate()
    chunks: list[dict[str, Any]] = []

    for page in pages:
        page_number = page["pageNumber"]
        text = page["text"]
        if not text or not text.strip():
            continue

        start = 0
        page_chunk_index = 0
        while start < len(text):
            end = _preferred_end(text, start, config.max_characters)
            raw_text = text[start:end]
            left_trim = len(raw_text) - len(raw_text.lstrip())
            right_trimmed_length = len(raw_text.rstrip())
            chunk_start = start + left_trim
            chunk_end = start + right_trimmed_length

            if chunk_start < chunk_end:
                if len(chunks) >= config.max_chunks:
                    raise ChunkLimitExceeded(
                        f"Document exceeds the {config.max_chunks}-chunk processing limit."
                    )
                chunk_number = len(chunks) + 1
                page_chunk_index += 1
                chunks.append(
                    {
                        "chunkId": f"{document_id}#chunk-{chunk_number:05d}",
                        "chunkIndex": chunk_number - 1,
                        "pageNumber": page_number,
                        "pageChunkIndex": page_chunk_index - 1,
                        "startCharacter": chunk_start,
                        "endCharacter": chunk_end,
                        "characterCount": chunk_end - chunk_start,
                        "text": text[chunk_start:chunk_end],
                    }
                )

            if end >= len(text):
                break

            next_start = max(end - config.overlap_characters, start + 1)
            if (
                next_start > 0
                and not text[next_start - 1].isspace()
                and not text[next_start].isspace()
            ):
                word_start = next_start
                while word_start > start and not text[word_start - 1].isspace():
                    word_start -= 1
                if word_start > start:
                    next_start = word_start
            while next_start < end and text[next_start].isspace():
                next_start += 1
            start = next_start

    return chunks
