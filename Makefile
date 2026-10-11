SHELL := /bin/sh
PYTHON ?= python3.12

AWS_REGION ?= us-east-1
AWS_PROFILE ?=
PROJECT_NAME ?= ai-study-assistant
ENVIRONMENT ?= dev
STACK_NAME ?= $(PROJECT_NAME)-$(ENVIRONMENT)-foundation
ARTIFACTS_STACK_NAME ?= $(PROJECT_NAME)-$(ENVIRONMENT)-artifacts
TEMPLATE := infrastructure/foundation.yaml
ARTIFACTS_TEMPLATE := infrastructure/artifacts.yaml
PROFILE_ARG := $(if $(AWS_PROFILE),--profile $(AWS_PROFILE),)
CREATE_UPLOAD_SOURCE := backend/functions/create_upload_url/handler.py
CREATE_UPLOAD_HASH := $(shell shasum -a 256 $(CREATE_UPLOAD_SOURCE) | cut -c1-16)
CREATE_UPLOAD_KEY := lambdas/create-upload-url/$(CREATE_UPLOAD_HASH).zip
CREATE_UPLOAD_ZIP := build/create-upload-url.zip
PROCESS_DOCUMENT_SOURCE := backend/functions/process_document/handler.py
CHUNKING_SOURCE := backend/shared/chunking.py
PROCESS_DOCUMENT_REQUIREMENTS := backend/functions/process_document/requirements.txt
PROCESS_DOCUMENT_HASH := $(shell shasum -a 256 $(PROCESS_DOCUMENT_SOURCE) $(CHUNKING_SOURCE) $(PROCESS_DOCUMENT_REQUIREMENTS) | shasum -a 256 | cut -c1-16)
PROCESS_DOCUMENT_KEY := lambdas/process-document/$(PROCESS_DOCUMENT_HASH).zip
PROCESS_DOCUMENT_ZIP := build/process-document.zip
BACKEND_TEST_DEPS := build/backend-test-deps

.PHONY: backend-deps backend-test infra-syntax infra-lint infra-validate artifacts-deploy \
	create-upload-package process-document-package lambda-package lambda-upload \
	infra-deploy infra-describe infra-delete \
	artifacts-delete

$(BACKEND_TEST_DEPS)/.installed: $(PROCESS_DOCUMENT_REQUIREMENTS)
	mkdir -p $(BACKEND_TEST_DEPS)
	$(PYTHON) -m pip install --disable-pip-version-check --no-compile \
		--target $(BACKEND_TEST_DEPS) -r $(PROCESS_DOCUMENT_REQUIREMENTS)
	touch $@

backend-deps: $(BACKEND_TEST_DEPS)/.installed

backend-test: backend-deps
	cd backend && PYTHONPATH=../$(BACKEND_TEST_DEPS):. $(PYTHON) -m unittest discover -s tests -v

infra-syntax:
	@ruby -e "require 'yaml'; YAML.parse_file('$(TEMPLATE)'); YAML.parse_file('$(ARTIFACTS_TEMPLATE)'); puts 'YAML syntax is valid.'"

infra-lint: infra-syntax
	cfn-lint $(TEMPLATE) $(ARTIFACTS_TEMPLATE)

infra-validate: infra-lint
	aws cloudformation validate-template \
		--template-body file://$(TEMPLATE) \
		--region $(AWS_REGION) \
		$(PROFILE_ARG) >/dev/null
	aws cloudformation validate-template \
		--template-body file://$(ARTIFACTS_TEMPLATE) \
		--region $(AWS_REGION) \
		$(PROFILE_ARG) >/dev/null
	@echo "CloudFormation accepted both templates."

artifacts-deploy: infra-validate
	aws cloudformation deploy \
		--template-file $(ARTIFACTS_TEMPLATE) \
		--stack-name $(ARTIFACTS_STACK_NAME) \
		--parameter-overrides ProjectName=$(PROJECT_NAME) Environment=$(ENVIRONMENT) \
		--no-fail-on-empty-changeset \
		--tags Project=$(PROJECT_NAME) Environment=$(ENVIRONMENT) \
		--region $(AWS_REGION) \
		$(PROFILE_ARG)

create-upload-package:
	rm -rf build/lambda-create-upload-url $(CREATE_UPLOAD_ZIP)
	mkdir -p build/lambda-create-upload-url
	cp $(CREATE_UPLOAD_SOURCE) build/lambda-create-upload-url/handler.py
	cd build/lambda-create-upload-url && zip -q ../create-upload-url.zip handler.py

process-document-package:
	rm -rf build/lambda-process-document $(PROCESS_DOCUMENT_ZIP)
	mkdir -p build/lambda-process-document
	$(PYTHON) -m pip install --disable-pip-version-check --no-compile \
		--target build/lambda-process-document -r $(PROCESS_DOCUMENT_REQUIREMENTS)
	cp $(PROCESS_DOCUMENT_SOURCE) build/lambda-process-document/handler.py
	mkdir -p build/lambda-process-document/shared
	cp $(CHUNKING_SOURCE) build/lambda-process-document/shared/chunking.py
	touch build/lambda-process-document/shared/__init__.py
	cd build/lambda-process-document && zip -qr ../process-document.zip .

lambda-package: create-upload-package process-document-package

lambda-upload: artifacts-deploy lambda-package
	artifact_bucket=$$(aws cloudformation describe-stacks \
		--stack-name $(ARTIFACTS_STACK_NAME) \
		--query 'Stacks[0].Outputs[?OutputKey==`ArtifactBucketName`].OutputValue | [0]' \
		--output text --region $(AWS_REGION) $(PROFILE_ARG)); \
	aws s3 cp $(CREATE_UPLOAD_ZIP) s3://$$artifact_bucket/$(CREATE_UPLOAD_KEY) \
		--only-show-errors --region $(AWS_REGION) $(PROFILE_ARG); \
	aws s3 cp $(PROCESS_DOCUMENT_ZIP) s3://$$artifact_bucket/$(PROCESS_DOCUMENT_KEY) \
		--only-show-errors --region $(AWS_REGION) $(PROFILE_ARG)

infra-deploy: lambda-upload
	artifact_bucket=$$(aws cloudformation describe-stacks \
		--stack-name $(ARTIFACTS_STACK_NAME) \
		--query 'Stacks[0].Outputs[?OutputKey==`ArtifactBucketName`].OutputValue | [0]' \
		--output text --region $(AWS_REGION) $(PROFILE_ARG)); \
	aws cloudformation deploy \
		--template-file $(TEMPLATE) \
		--stack-name $(STACK_NAME) \
		--parameter-overrides \
			ProjectName=$(PROJECT_NAME) \
			Environment=$(ENVIRONMENT) \
			LambdaArtifactBucketName=$$artifact_bucket \
			CreateUploadUrlArtifactKey=$(CREATE_UPLOAD_KEY) \
			ProcessDocumentArtifactKey=$(PROCESS_DOCUMENT_KEY) \
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

artifacts-delete:
	artifact_bucket=$$(aws cloudformation describe-stacks \
		--stack-name $(ARTIFACTS_STACK_NAME) \
		--query 'Stacks[0].Outputs[?OutputKey==`ArtifactBucketName`].OutputValue | [0]' \
		--output text --region $(AWS_REGION) $(PROFILE_ARG)); \
	aws s3 rm s3://$$artifact_bucket --recursive --only-show-errors \
		--region $(AWS_REGION) $(PROFILE_ARG)
	aws cloudformation delete-stack \
		--stack-name $(ARTIFACTS_STACK_NAME) \
		--region $(AWS_REGION) \
		$(PROFILE_ARG)
	aws cloudformation wait stack-delete-complete \
		--stack-name $(ARTIFACTS_STACK_NAME) \
		--region $(AWS_REGION) \
		$(PROFILE_ARG)
