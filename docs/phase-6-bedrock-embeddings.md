# Phase 6: Amazon Bedrock Text Embeddings

Phase 6 converts each page-aware text chunk into a numerical vector. Texts with
similar meaning should produce vectors that are near each other, allowing the
later OpenSearch phase to retrieve relevant course material even when a
student's wording differs from the PDF.

## Model selection

The development deployment uses the active on-demand model
`amazon.titan-embed-text-v2:0` in `us-east-1`. It requests normalized vectors
with 1,024 dimensions. A direct account-level invocation was tested before the
pipeline was deployed.

The model ID, dimensions, and normalization are CloudFormation parameters and
Lambda environment variables. This keeps model choice out of application code
and allows the vector index configuration to use the same dimensions.

## Asynchronous data flow

```text
processing/<document-id>/chunks.json
                    |
                    v
        EventBridge suffix filter
                    |
                    v
        generate-embeddings Lambda
                    |
                    +----> Amazon Bedrock InvokeModel
                    |
                    v
processing/<document-id>/embeddings.json
processing/<document-id>/status.json  (EMBEDDED)
```

Embedding is separate from PDF processing because model calls need distinct IAM
permissions, retries, timeouts, observability, and cost controls. The function
has a five-minute timeout and accepts at most 500 chunks in one invocation by
default. Larger-scale production ingestion could distribute chunks through a
queue or use batch inference.

## Validation and output contract

Before invoking Bedrock, the Lambda validates the event, exact S3 key shape,
matching `CHUNKED` completion status, artifact size, JSON schema, document
identity, deterministic chunk IDs and indexes, page numbers, text, and character
counts. If the S3 event arrives before the completion status, the Lambda raises
a temporary error so EventBridge retries instead of relying on timing.

For every model response it verifies:

- the vector is a list with exactly the configured dimensions;
- every value is numeric and finite; and
- the optional input-token count is a non-negative integer.

Only after all chunks succeed does it write `embeddings.json`, followed by
`status.json` as the completion marker. Each result preserves the chunk ID,
index, page number, token count, and vector. Permanent input problems produce a
`FAILED` status for the `EMBEDDING` stage. AWS and Bedrock runtime failures are
raised so EventBridge can retry them twice within one hour.

## Security and cost boundary

The dedicated role can only:

- read `processing/*/chunks.json` and `processing/*/status.json`;
- write `processing/*/embeddings.json` and `processing/*/status.json`;
- invoke the configured foundation-model ARN; and
- write its own retained CloudWatch logs.

Bedrock is usage-priced, and one model invocation is made per chunk. The chunk
limit bounds the work and cost of a single event. No document text or embedding
vector is written to logs.

## References

- [Amazon Titan Text Embeddings models](https://docs.aws.amazon.com/bedrock/latest/userguide/titan-embedding-models.html)
- [Titan Text Embeddings request and response](https://docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-titan-embed-text.html)
- [Access Amazon Bedrock foundation models](https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html)
