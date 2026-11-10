# Phase 9: Semantic Retrieval

Phase 9 adds the read side of the vector pipeline. A question is embedded with
the same configurable Titan Text Embeddings V2 model and dimensions used for
document chunks. The resulting vector is sent to the OpenSearch Serverless
`_search` API using a k-nearest-neighbor query against `chunk_vector`.

## Retrieval contract

The reusable `shared/retrieval.py` module:

1. validates and bounds the question, result count, score threshold, and up to
   20 optional document IDs;
2. creates a normalized query vector through Amazon Bedrock;
3. uses a SigV4 `aoss` request to search the configured index;
4. applies document filters inside the k-NN query for efficient filtering;
5. excludes vectors from `_source` to reduce response size; and
6. returns ranked chunk text, document ID, chunk ID, page number, and score.

Retrieval is separate from answer generation. This makes ranking testable and
lets chat, summaries, study guides, and practice questions share the same
grounding behavior.

The default top-k is 5 and the initial minimum score is 0.6. These values are
configuration, not universal truth; Phase 17 end-to-end evaluation can tune the
threshold against representative course material.

## References

- [OpenSearch Serverless vector search](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless-vector-search.html)
- [OpenSearch filtered k-NN search](https://docs.opensearch.org/latest/vector-search/filter-search-knn/efficient-knn-filtering/)
