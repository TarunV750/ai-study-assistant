# Phase 13: study tools

`POST /study` now creates source-grounded summaries, key-concept reviews, practice questions, and study guides. The request can filter to selected document IDs and optionally focus on a topic. Practice questions support multiple-choice, short-answer, or mixed formats.

The service first retrieves semantically relevant passages, then gives only those passages to Bedrock. This makes the output traceable and bounds prompt size. It is a retrieval-based view of the material, not an exhaustive full-document summary; the returned source list makes that limitation visible.

Study generation requires at least one explicitly selected indexed document. Unlike a narrow Q&A query, broad study modes use a separately configurable retrieval floor (zero by default) and up to ten top-ranked passages from those selected documents. This prevents a general “study guide” query from incorrectly rejecting an otherwise valid course PDF while preserving the stricter relevance threshold for question answering.
