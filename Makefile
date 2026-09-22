SHELL := /bin/sh

AWS_REGION ?= us-east-1
AWS_PROFILE ?=
PROJECT_NAME ?= ai-study-assistant
ENVIRONMENT ?= dev
STACK_NAME ?= $(PROJECT_NAME)-$(ENVIRONMENT)-foundation
TEMPLATE := infrastructure/foundation.yaml
PROFILE_ARG := $(if $(AWS_PROFILE),--profile $(AWS_PROFILE),)

.PHONY: infra-syntax infra-lint infra-validate infra-deploy infra-describe infra-delete

infra-syntax:
	@ruby -e "require 'yaml'; YAML.parse_file('$(TEMPLATE)'); puts 'YAML syntax is valid.'"

infra-lint: infra-syntax
	cfn-lint $(TEMPLATE)

infra-validate: infra-lint
	aws cloudformation validate-template \
		--template-body file://$(TEMPLATE) \
		--region $(AWS_REGION) \
		$(PROFILE_ARG) >/dev/null
	@echo "CloudFormation accepted $(TEMPLATE)."

infra-deploy: infra-validate
	aws cloudformation deploy \
		--template-file $(TEMPLATE) \
		--stack-name $(STACK_NAME) \
		--parameter-overrides \
			ProjectName=$(PROJECT_NAME) \
			Environment=$(ENVIRONMENT) \
		--capabilities CAPABILITY_IAM \
		--no-fail-on-empty-changeset \
		--tags Project=$(PROJECT_NAME) Environment=$(ENVIRONMENT) \
		--region $(AWS_REGION) \
		$(PROFILE_ARG)

infra-describe:
	aws cloudformation describe-stacks \
		--stack-name $(STACK_NAME) \
		--query 'Stacks[0].{Status:StackStatus,Outputs:Outputs}' \
		--output table \
		--region $(AWS_REGION) \
		$(PROFILE_ARG)

infra-delete:
	aws cloudformation delete-stack \
		--stack-name $(STACK_NAME) \
		--region $(AWS_REGION) \
		$(PROFILE_ARG)
	aws cloudformation wait stack-delete-complete \
		--stack-name $(STACK_NAME) \
		--region $(AWS_REGION) \
		$(PROFILE_ARG)
