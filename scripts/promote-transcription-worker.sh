#!/usr/bin/env bash
# Promotes a freshly-pushed sha-tagged image (built by .github/workflows/deploy.yml) into the
# current AWS account: writes the per-tier image tag to SSM and registers a new task-definition
# revision per tier. The dispatcher Lambda runs tasks by FAMILY (D-157), so it picks up the new
# revision automatically — no pipe/target/service update step. There is no ECS Service in this
# architecture (RunTask is invoked per job, D-066) — no `update-service` step either.
#
# Usage: promote-transcription-worker.sh <sha-tag>   (e.g. sha-abc1234)
# Requires AWS credentials for the target account already configured in the environment.
set -euo pipefail

SHA_TAG="${1:?usage: promote-transcription-worker.sh <sha-tag>}"
ECR_REPO="313828097088.dkr.ecr.eu-west-1.amazonaws.com/heediq-worker-transcription"

promote_tier() {
  local tier=$1
  local image="${ECR_REPO}:${tier}-${SHA_TAG}"
  local family="heediq-transcription-${tier}"
  local ssm_param="/heediq/transcription/${tier}-image-tag"

  echo "[${tier}] promoting ${image}"

  # CDK reads this via a CloudFormation dynamic reference at deploy time — CI owns the value, so
  # a routine `cdk deploy` for unrelated infra changes never rolls a promoted image back to the
  # bootstrap tag (see heediq-infra TranscriptionStack).
  aws ssm put-parameter --name "$ssm_param" --value "${tier}-${SHA_TAG}" --type String --overwrite

  local task_def new_task_def new_arn
  task_def=$(aws ecs describe-task-definition --task-definition "$family" --query 'taskDefinition')
  new_task_def=$(echo "$task_def" | jq --arg IMAGE "$image" \
    '.containerDefinitions[0].image = $IMAGE
     | del(.taskDefinitionArn, .revision, .status, .requiresAttributes, .compatibilities, .registeredAt, .registeredBy)')
  new_arn=$(aws ecs register-task-definition --cli-input-json "$new_task_def" --query 'taskDefinition.taskDefinitionArn' --output text)

  echo "[${tier}] registered ${new_arn} — dispatcher runs by family, picks it up on the next job"
}

promote_tier free
promote_tier paid
