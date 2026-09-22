# ADR 0002: CloudFormation with one execution role per Lambda

- **Status:** Accepted
- **Date:** 2026-09-22

## Context

The AWS environment must be reproducible and understandable to a student. The
local machine has AWS CLI v2 but not AWS SAM CLI, AWS CDK, Node.js, or a Python
3.12 development runtime. The backend will contain functions with materially
different access needs.

## Decision

Use plain AWS CloudFormation as the infrastructure source of truth. Give each
Lambda responsibility a dedicated IAM execution role and CloudWatch log group.
Start the roles with only scoped logging authorization and add permissions in
the phase that introduces each service call.

## Consequences

- Infrastructure can be validated and deployed with AWS CLI v2 alone.
- IAM reviews show exactly which function can access each resource.
- A compromised handler has a smaller authorization scope.
- The template is more repetitive than a shared execution role.
- Lambda artifact packaging must be introduced explicitly when functions are
  deployed; adopting SAM later remains possible if it provides clear value.
