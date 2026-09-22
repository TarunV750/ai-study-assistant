# Infrastructure

The project uses AWS CloudFormation so the deployed environment is repeatable,
reviewable, and removable as a stack. Phase 2 introduces `foundation.yaml`.

## What the foundation creates

- One execution role for each future Lambda responsibility
- One CloudWatch log group for each future Lambda
- Inline logging permissions scoped to each role's own log group
- A configurable log-retention period, defaulting to 14 days
- An optional IAM permissions boundary for managed AWS accounts

It deliberately does **not** create Lambda functions, S3 storage, API Gateway,
Bedrock resources, or an OpenSearch Serverless collection yet. Those resources
and permissions will be added when their behavior is implemented and testable.

## Why five roles instead of one

The upload function will eventually need limited S3 write authorization, while
the document processor will need S3 read, Bedrock embedding, and OpenSearch
indexing authorization. Question answering needs a different combination. A
separate role per function prevents one compromised function from inheriting
every backend permission.

The roles currently have only:

```text
logs:CreateLogStream
logs:PutLogEvents
```

Both actions are restricted to that function's pre-created log group. The roles
do not need `logs:CreateLogGroup` because CloudFormation creates the groups.

## Prerequisites

1. An AWS account intended for development.
2. AWS CLI v2.
3. Authenticated CLI credentials with CloudFormation, IAM-role, and CloudWatch
   Logs administration permissions for this stack.
4. A chosen AWS Region. `us-east-1` is the development default, but confirm all
   required Bedrock models and OpenSearch Serverless features in your Region
   before later phases.

Check your identity before deploying:

```bash
aws sts get-caller-identity --profile YOUR_PROFILE --region us-east-1
```

Never put access keys in this repository or the React application. Prefer AWS
IAM Identity Center (`aws configure sso`) or temporary credentials.

## Validate locally and with AWS

From the repository root:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r infrastructure/requirements-dev.txt
make infra-syntax
make infra-lint
make infra-validate AWS_PROFILE=YOUR_PROFILE AWS_REGION=us-east-1
```

`infra-syntax` checks YAML locally. `infra-lint` applies the CloudFormation
resource specification and best-practice rules. `infra-validate` then asks the
AWS CloudFormation service to validate the template and therefore requires
authenticated AWS access.

## Deploy

Review the proposed change set before creating resources:

```bash
aws cloudformation deploy \
  --template-file infrastructure/foundation.yaml \
  --stack-name ai-study-assistant-dev-foundation \
  --parameter-overrides ProjectName=ai-study-assistant Environment=dev \
  --capabilities CAPABILITY_IAM \
  --no-execute-changeset \
  --region us-east-1 \
  --profile YOUR_PROFILE
```

The command prints the generated change-set name. Inspect it in the AWS
CloudFormation console. Then deploy using the convenience command:

```bash
make infra-deploy AWS_PROFILE=YOUR_PROFILE AWS_REGION=us-east-1
make infra-describe AWS_PROFILE=YOUR_PROFILE AWS_REGION=us-east-1
```

`CAPABILITY_IAM` is an explicit acknowledgement that the template creates IAM
roles. CloudFormation generates the physical role names, which avoids global
name collisions between accounts or environments.

If your account mandates a permissions boundary, deploy directly and include:

```text
PermissionsBoundaryArn=arn:aws:iam::ACCOUNT_ID:policy/BOUNDARY_NAME
```

in `--parameter-overrides`.

## Verify in AWS

```bash
aws cloudformation describe-stacks \
  --stack-name ai-study-assistant-dev-foundation \
  --query 'Stacks[0].StackStatus' \
  --output text \
  --region us-east-1 \
  --profile YOUR_PROFILE

aws logs describe-log-groups \
  --log-group-name-prefix /aws/lambda/ai-study-assistant-dev \
  --query 'logGroups[].{name:logGroupName,retention:retentionInDays}' \
  --region us-east-1 \
  --profile YOUR_PROFILE
```

The expected stack status is `CREATE_COMPLETE`; five log groups should appear,
each with a retention value of 14.

## Costs and cleanup

IAM roles and the empty log groups themselves do not incur charges. CloudWatch
Logs charges for ingestion and stored log data only after functions begin
writing logs. The 14-day retention period prevents indefinite log storage.

Delete this foundation when it is no longer needed:

```bash
make infra-delete AWS_PROFILE=YOUR_PROFILE AWS_REGION=us-east-1
```

Later phases will add resources with material charges, especially Amazon
OpenSearch Serverless and Amazon Bedrock inference. Their deployment and cleanup
steps will be called out before creation.
