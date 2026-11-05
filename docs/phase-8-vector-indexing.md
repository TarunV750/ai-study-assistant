# Phase 8: Chunk and Embedding Indexing

Phase 8 turns the validated S3 artifacts from Phases 5 and 6 into searchable
OpenSearch documents. A dedicated Lambda receives creation events for
`processing/<document-id>/embeddings.json`, joins each vector to its source
chunk, and writes the result to the `study-assistant-chunks` index.

## Data flow

1. S3 publishes creation of `embeddings.json` to EventBridge.
2. EventBridge invokes `index-document` with at-least-once delivery.
3. The Lambda waits for the matching `EMBEDDED` status marker so it cannot race
   the embedding Lambda's final write.
4. It loads `chunks.json` and `embeddings.json` and validates both contracts.
5. It creates the vector index if it does not already exist.
6. It sends bounded OpenSearch Bulk API requests and writes `INDEXED` status
   only after every batch succeeds.

The index contains chunk text, page and character offsets, document and chunk
identifiers, the embedding model ID, and the 1,024-dimension vector. The vector
field uses cosine similarity, which matches the normalized Titan Text
Embeddings V2 output used by this project.

## Idempotency and retries

EventBridge can deliver an event more than once. Each OpenSearch `_id` is the
deterministic chunk ID produced in Phase 5, and the bulk operation uses
`index`, so retrying replaces the same logical document instead of adding a
duplicate. Both `EMBEDDED` and the already completed `INDEXED` marker are valid
retry starting states. Index creation first uses `HEAD`, then tolerates a concurrent
`resource_already_exists_exception` from another first-document invocation.

Permanent artifact errors produce a structured `FAILED` status with stage
`INDEXING`. Transient S3 or OpenSearch errors are raised so EventBridge can
retry them.

## Validation boundary

Before indexing, the Lambda verifies:

- both artifacts use schema version 1 and the event's document ID;
- status, chunk counts, IDs, indexes, and page numbers match;
- source offsets and character counts agree with the stored text;
- every vector has the configured dimensions and only finite numeric values;
- document, artifact-size, and bulk-batch limits are respected.

## Access control

OpenSearch Serverless uses two authorization layers. The Lambda role has the
IAM action `aoss:APIAccessAll` scoped to the one collection ARN. The collection
data policy then narrows that principal to `CreateIndex`, `DescribeIndex`, and
`WriteDocument` on one exact index. It does not receive read access, collection
administration, Dashboards access, or access to other indexes.

The role can read only chunk, embedding, and status artifacts and can write
only final status records. All OpenSearch requests use Signature Version 4
with service name `aoss` and include the payload hash required by Serverless.

## Index ownership decision

The first deployment attempted the native `AWS::OpenSearchServerless::Index`
resource. CloudFormation's resource provider created the index as the
deployment identity, which the deliberately narrow data policy did not trust,
so AWS returned `Access denied for operation 'CreateIndex'` and rolled the
stack back cleanly.

Granting the human deployment user permanent data access would weaken the
design. Instead, index creation is idempotent application initialization under
the dedicated runtime role. CloudFormation still owns the collection, role,
policy, event rule, configuration, and Lambda package.

## References

- [Working with vector search collections](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless-vector-search.html)
- [OpenSearch Serverless data access control](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless-data-access.html)
- [Troubleshooting OpenSearch Serverless authentication](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless-troubleshooting.html)
- [Ingesting data into Serverless collections](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless-clients.html)
