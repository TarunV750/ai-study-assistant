# Phase 2 Development Deployment

- **Date:** 2026-09-22
- **Region:** `us-east-1`
- **Stack:** `ai-study-assistant-dev-foundation`
- **Final status:** `CREATE_COMPLETE`
- **Template:** `infrastructure/foundation.yaml`
- **Template validation:** AWS CloudFormation accepted the template

## Change-set review

The reviewed change set contained ten additions and no modifications,
replacements, or deletions:

- Five `AWS::IAM::Role` resources
- Five `AWS::Logs::LogGroup` resources

No Lambda, S3, API Gateway, Bedrock, or OpenSearch Serverless resources were
created in this phase.

## Post-deployment verification

After CloudFormation completed, AWS API queries confirmed:

- exactly five IAM roles and five CloudWatch log groups belong to the stack;
- all five log groups use 14-day retention;
- all five role trust policies name only `lambda.amazonaws.com` as the service
  principal;
- each role has one inline policy named `WriteOwnCloudWatchLogs`;
- each inline policy contains `logs:CreateLogStream` and `logs:PutLogEvents`;
- no application-service permissions have been granted yet.

Account identifiers, role ARNs, and credentials are intentionally excluded from
this record.

## Reproduce the verification

```bash
make infra-describe AWS_REGION=us-east-1

aws logs describe-log-groups \
  --log-group-name-prefix /aws/lambda/ai-study-assistant-dev \
  --query 'logGroups[].{name:logGroupName,retention:retentionInDays}' \
  --region us-east-1 \
  --output table
```

These commands use the currently authenticated AWS CLI identity. Add
`AWS_PROFILE=YOUR_PROFILE` to the `make` command and `--profile YOUR_PROFILE` to
the AWS CLI command when using a named profile.
