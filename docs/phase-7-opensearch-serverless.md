# Phase 7: Amazon OpenSearch Serverless Vector Foundation

Phase 7 provisions the managed vector-search boundary that later phases will
use to store and retrieve Bedrock embeddings. It creates the collection and its
security/capacity policies only; Phase 8 creates the concrete vector index and
writes documents.

## Resources

```text
NEXTGEN collection group (0-2 indexing OCUs, 0-2 search OCUs)
                              |
                              v
                 VECTORSEARCH collection
                  /          |          \
        encryption       network       data access
          policy          policy          policy
```

The development defaults are:

- collection: `ai-study-dev-vectors`;
- collection group: `ai-study-dev-vector-group`;
- collection type: `VECTORSEARCH`;
- minimum capacity: zero indexing and zero search OCUs;
- maximum capacity: two indexing and two search OCUs;
- high availability: enabled as required by next-generation groups;
- vector path: standard index behavior without requesting acceleration; and
- deletion protection: disabled for repeatable development cleanup.

Both names are CloudFormation parameters because OpenSearch names are globally
constrained within an account and Region.

## Security policies

The encryption policy uses an AWS-owned key. This avoids an additional KMS key
while still providing encryption at rest; a production environment can switch
to a customer-managed key when key ownership or rotation requirements demand
it.

The API endpoint is publicly reachable so the current non-VPC Lambdas can use
it in later phases. This does not make collection data public. OpenSearch
Serverless requires SigV4-authenticated IAM authorization and a matching data
access policy. The data policy names only the embedding role and scopes it to
this collection and its indexes.

The role deliberately does not receive `aoss:APIAccessAll` in Phase 7, so it has
no effective data-plane access yet. Phase 8 will add the IAM permission when it
also implements index creation and writes. A production design can replace the
public network policy with an OpenSearch Serverless-managed VPC endpoint.

## Cost controls

The next-generation collection group can scale to zero OCUs for indexing and
search while idle. Maximums of two OCUs on each side bound unexpected scaling.
At deployment time, the AWS Price List API reported `$0.24` per OCU-hour in
`us-east-1`; fully using both maximums would therefore reach `$0.96` per hour,
plus storage. Actual billing is based on used capacity and storage, and prices
can change.

Scale-to-zero can introduce cold-start latency on the first indexing or search
operation after an idle period. That tradeoff is appropriate for this portfolio
development environment.

## Phase boundary

No OpenSearch index exists after this phase. This makes the infrastructure
boundary independently verifiable without mixing collection security with
mapping design. Phase 8 will create an index whose vector dimensions match the
1,024-dimensional Titan output, then index text and citation metadata alongside
each vector.

## References

- [OpenSearch Serverless overview](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless-overview.html)
- [Managing OpenSearch Serverless capacity](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless-scaling.html)
- [CloudFormation collection groups](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-opensearchserverless-collectiongroup.html)
- [OpenSearch Service pricing](https://aws.amazon.com/opensearch-service/pricing/)
