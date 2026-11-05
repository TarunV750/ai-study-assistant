# Phase 8 Development Deployment

Phase 8 was deployed to the existing `dev` foundation stack in `us-east-1`.
No account IDs, collection endpoints, bucket names, or credentials are stored
in this record.

## Result

- Foundation stack status: `UPDATE_COMPLETE`
- Vector index: `study-assistant-chunks`
- Embedding dimensions: 1,024
- Similarity space: cosine
- Trigger: S3 Object Created event for `/embeddings.json` through EventBridge
- Final successful status: `INDEXED`
- Automated backend tests: 42 passing
- Local CloudFormation lint: passing
- AWS template validation: passing

## Live verification

An isolated one-chunk artifact was uploaded under a new test document prefix.
The existing embedding Lambda generated a real 1,024-dimension Titan vector.
EventBridge then invoked the Phase 8 indexer, which created the index, wrote the
chunk, and changed the S3 completion marker from `EMBEDDED` to `INDEXED`.
CloudWatch recorded `document_indexed` with `chunk_count: 1`.

The same embedding event was then invoked again after the status was already
`INDEXED`. It returned HTTP 200 and `INDEXED` with the same one-chunk count,
confirming live at-least-once delivery is idempotent.

The deployed data policy was inspected after the test. It grants the indexer
role only `CreateIndex`, `DescribeIndex`, and `WriteDocument` on the exact
collection/index path. The role's IAM permission is scoped to the collection
ARN.

## Deployment correction

The first reviewed change set included the newly available native
`AWS::OpenSearchServerless::Index` resource. Its create operation ran as the
deployment identity rather than the dedicated indexer role, so the narrow data
policy correctly denied it. CloudFormation reached
`UPDATE_ROLLBACK_COMPLETE` without leaving the attempted index or new Lambda
resources behind.

The corrected change set removed the native index resource and placed
idempotent create-if-missing behavior in the indexer. The second change set
contained five additions and one in-place data-policy update, with no
replacements or deletions, and completed successfully.

## Cost note

The live embedding and indexing test can incur small Bedrock, Lambda, S3,
CloudWatch, EventBridge, and OpenSearch charges. The NextGen collection group
still has zero minimum indexing and search capacity, so it can return to zero
OCUs while idle.
