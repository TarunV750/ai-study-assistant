# Phase 7 Development Deployment

- **Date:** 2026-10-10 local time / 2026-10-11 UTC
- **Region:** `us-east-1`
- **Foundation stack:** `ai-study-assistant-dev-foundation` — `UPDATE_COMPLETE`
- **Collection:** `ai-study-dev-vectors` — `ACTIVE`
- **Collection type:** `VECTORSEARCH`
- **Collection group:** `ai-study-dev-vector-group` — `NEXTGEN`
- **Template validation:** local `cfn-lint` and AWS CloudFormation validation
  passed

## Cost check

Before deployment, the account contained no OpenSearch Serverless collections
or collection groups. The AWS Price List API reported `$0.24` per OCU-hour for
both indexing and search in `us-east-1` and `$0.024` per GB-month for serverless
storage at the time of deployment.

The collection group was configured with zero minimum indexing and search OCUs
and maximums of two OCUs for each. This permits scale-to-zero while idle and
bounds full simultaneous indexing/search compute at four OCUs.

## Reviewed changes

The reviewed successful change set contained five additions and no
modifications, replacements, or deletions:

- one next-generation collection group;
- one `VECTORSEARCH` collection;
- one AWS-owned-key encryption policy;
- one authenticated public-endpoint network policy; and
- one least-privilege data-access policy.

An output-only follow-up corrected the collection-name stack output without
changing any resources.

## Deployment corrections

Two earlier updates rolled back completely before the successful deployment:

1. OpenSearch Serverless rejected `StandbyReplicas=DISABLED` because
   next-generation collection groups require their built-in high-availability
   setting.
2. It rejected an explicit vector-acceleration value because that setting
   cannot be modified for a next-generation collection.

CloudFormation canceled or removed all five resources during both rollbacks.
Control-plane checks confirmed that no collection or collection group remained
before the corrected attempt. The template now uses the required
high-availability value and leaves acceleration unspecified for the standard
vector-index path.

## Live verification

AWS API checks confirmed:

- the collection is `ACTIVE` and attached to the intended collection group;
- the group generation is `NEXTGEN`;
- minimum indexing/search capacity is `0` OCUs;
- maximum indexing/search capacity is `2` OCUs each;
- high availability is enabled as required by the group generation;
- encryption uses an AWS-owned key;
- the network policy exposes only the collection API resource;
- the data policy names only the embedding role and exact collection/index
  patterns; and
- an unsigned `/_cat/indices` request returns HTTP 403.

No vector index or document was created in this phase. That work belongs to
Phase 8. Account identifiers, collection IDs, endpoints, and credentials are
intentionally excluded from this record.

## Automated verification

All 33 existing backend regression tests pass. Both CloudFormation templates
pass YAML parsing, `cfn-lint`, and AWS validation. The narrowly scoped local
linter exceptions on the two OpenSearch resources cover only newly documented
CloudFormation properties not yet present in the installed linter schema.
