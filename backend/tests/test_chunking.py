"""Tests for deterministic, page-aware text chunking."""

import unittest

from shared.chunking import (
    ChunkingConfig,
    ChunkingConfigurationError,
    ChunkLimitExceeded,
    chunk_pages,
)

DOCUMENT_ID = "123e4567-e89b-42d3-a456-426614174000"


class ChunkingTests(unittest.TestCase):
    def config(self, *, size=30, overlap=8, limit=100):
        return ChunkingConfig(
            max_characters=size,
            overlap_characters=overlap,
            max_chunks=limit,
        )

    def test_short_page_becomes_one_chunk_with_traceable_offsets(self):
        chunks = chunk_pages(
            [{"pageNumber": 3, "text": "A concise paragraph."}],
            document_id=DOCUMENT_ID,
            config=self.config(),
        )

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["chunkId"], f"{DOCUMENT_ID}#chunk-00001")
        self.assertEqual(chunks[0]["pageNumber"], 3)
        self.assertEqual(chunks[0]["startCharacter"], 0)
        self.assertEqual(chunks[0]["endCharacter"], 20)
        self.assertEqual(chunks[0]["text"], "A concise paragraph.")

    def test_long_page_has_overlap_and_prefers_whitespace(self):
        text = "alpha bravo charlie delta echo foxtrot golf hotel india juliet"
        chunks = chunk_pages(
            [{"pageNumber": 1, "text": text}],
            document_id=DOCUMENT_ID,
            config=self.config(size=25, overlap=7),
        )

        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(chunk["characterCount"], 25)
            self.assertEqual(
                chunk["text"],
                text[chunk["startCharacter"] : chunk["endCharacter"]],
            )
        for previous, current in zip(chunks, chunks[1:], strict=False):
            self.assertLess(current["startCharacter"], previous["endCharacter"])
            self.assertEqual(current["text"][0].isspace(), False)
            self.assertTrue(
                current["startCharacter"] == 0
                or text[current["startCharacter"] - 1].isspace()
            )

    def test_chunks_never_cross_page_boundaries(self):
        chunks = chunk_pages(
            [
                {"pageNumber": 1, "text": "page one " * 8},
                {"pageNumber": 2, "text": "page two " * 8},
            ],
            document_id=DOCUMENT_ID,
            config=self.config(size=24, overlap=6),
        )

        page_numbers = [chunk["pageNumber"] for chunk in chunks]
        self.assertIn(1, page_numbers)
        self.assertIn(2, page_numbers)
        self.assertTrue(all("page two" not in c["text"] for c in chunks if c["pageNumber"] == 1))
        self.assertTrue(all("page one" not in c["text"] for c in chunks if c["pageNumber"] == 2))

    def test_blank_pages_are_skipped_and_indexes_remain_contiguous(self):
        chunks = chunk_pages(
            [
                {"pageNumber": 1, "text": ""},
                {"pageNumber": 2, "text": "Useful text"},
                {"pageNumber": 3, "text": "   "},
            ],
            document_id=DOCUMENT_ID,
            config=self.config(),
        )

        self.assertEqual([chunk["chunkIndex"] for chunk in chunks], [0])
        self.assertEqual(chunks[0]["pageNumber"], 2)

    def test_long_word_uses_hard_character_boundary(self):
        text = "x" * 75
        chunks = chunk_pages(
            [{"pageNumber": 1, "text": text}],
            document_id=DOCUMENT_ID,
            config=self.config(size=30, overlap=5),
        )

        self.assertEqual([chunk["characterCount"] for chunk in chunks], [30, 30, 25])
        self.assertEqual(chunks[1]["startCharacter"], 25)

    def test_chunk_limit_is_enforced(self):
        with self.assertRaisesRegex(ChunkLimitExceeded, "2-chunk"):
            chunk_pages(
                [{"pageNumber": 1, "text": "x" * 100}],
                document_id=DOCUMENT_ID,
                config=self.config(size=30, overlap=5, limit=2),
            )

    def test_invalid_configuration_is_rejected(self):
        invalid_configs = [
            self.config(size=0),
            self.config(size=20, overlap=-1),
            self.config(size=20, overlap=20),
            self.config(limit=0),
        ]

        for config in invalid_configs:
            with self.subTest(config=config):
                with self.assertRaises(ChunkingConfigurationError):
                    config.validate()


if __name__ == "__main__":
    unittest.main()
