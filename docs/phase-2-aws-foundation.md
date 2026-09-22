# Phase 2: AWS Foundation and IAM

## Learning goals

This phase separates two ideas that are often conflated:

- A Lambda **function** is executable code plus runtime configuration.
- A Lambda **execution role** is the AWS identity assumed by that code.

The role answers “what may this code do?” It does not grant the person deploying
the stack permission to deploy it; deployment credentials are a separate
control-plane identity.

## Trust policy versus permissions policy

Every role in `infrastructure/foundation.yaml` has two policy concepts:

1. The trust policy permits the `lambda.amazonaws.com` service principal to
   call `sts:AssumeRole`.
2. The inline permissions policy permits the assumed role to create a stream
   and publish events only inside its own CloudWatch log group.

A trust policy alone grants no access to S3, Bedrock, or OpenSearch. A permissions
policy is also required, and the service must enforce it against the requested
resource.

## Why CloudWatch log groups are explicit

Lambda can create a default log group on first invocation, but that requires
`logs:CreateLogGroup` against a broad resource scope. Pre-creating each group:

- lets CloudFormation own its lifecycle;
- permits narrowly scoped runtime logging access;
- configures retention before the first invocation; and
- gives every environment a predictable log location.

## IAM permission growth plan

| Role | Phase 2 | Permissions added later |
| --- | --- | --- |
| Create upload URL | Own logs | Scoped `s3:PutObject` signing authorization |
| Process document | Own logs | Scoped S3 read, Bedrock embedding invoke, OpenSearch write |
| Ask question | Own logs | Bedrock embedding/generation invoke, OpenSearch read |
| Generate questions | Own logs | Bedrock embedding/generation invoke, OpenSearch read |
| Manage documents | Own logs | Scoped S3 and OpenSearch list/delete operations |

The exact resource ARNs will be referenced from CloudFormation resources, not
represented as `*`, wherever the target service supports resource-level IAM.

## Current AWS details verified

The design was checked against current AWS documentation before implementation:

- Lambda needs `logs:CreateLogStream` and `logs:PutLogEvents` to write to a
  pre-created CloudWatch log group.
- Bedrock inference will later require `bedrock:InvokeModel`, scoped to selected
  model or inference-profile ARNs.
- OpenSearch Serverless later requires both a data access policy and IAM data
  plane authorization such as `aoss:APIAccessAll`; either one alone is
  insufficient.
- Current NextGen OpenSearch Serverless collection groups support minimum
  indexing/search capacity of zero and maximum capacity controls. We will use
  those controls in Phase 7 rather than creating an uncapped collection now.

Official references:

- [Lambda CloudWatch log groups](https://docs.aws.amazon.com/lambda/latest/dg/monitoring-cloudwatchlogs-loggroups.html)
- [Bedrock identity-policy examples](https://docs.aws.amazon.com/bedrock/latest/userguide/security_iam_id-based-policy-examples.html)
- [OpenSearch Serverless IAM](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/security-iam-serverless.html)
- [OpenSearch Serverless collection-group capacity](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/collection-groups-capacity-limits.html)
