#!/usr/bin/env bash
# Run a one-off WorkflowEngine CLI command as an ECS task on the API image, wait for it, print
# its logs.
#   scripts/aws-run-task.sh <aws-dev|aws-prod> wfe migrate
#   scripts/aws-run-task.sh aws-dev wfe user create --email you@example.com --name You --admin
set -euo pipefail
ENV="${1:?usage: aws-run-task.sh <env> <command...>}"; shift
DIR="$(cd "$(dirname "$0")/.." && pwd)/infra/terraform/envs/$ENV"
out() { terraform -chdir="$DIR" output -raw "$1"; }
cluster=$(out cluster_name)
taskdef=$(out cli_task_definition)
group=$(out cli_security_group_id)
subnets=$(terraform -chdir="$DIR" output -json private_subnet_ids | tr -d ' "[]')
cmd=$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' "$@")

arn=$(aws ecs run-task --cluster "$cluster" --task-definition "$taskdef" --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$subnets],securityGroups=[$group],assignPublicIp=DISABLED}" \
  --overrides "{\"containerOverrides\":[{\"name\":\"cli\",\"command\":$cmd}]}" \
  --query 'tasks[0].taskArn' --output text)
echo "started $arn"
aws ecs wait tasks-stopped --cluster "$cluster" --tasks "$arn"
code=$(aws ecs describe-tasks --cluster "$cluster" --tasks "$arn" --query 'tasks[0].containers[0].exitCode' --output text)
logs=$(aws ecs describe-task-definition --task-definition "$taskdef" --query 'taskDefinition.containerDefinitions[0].logConfiguration.options."awslogs-group"' --output text)
aws logs tail "$logs" --since 15m --format short | tail -40
echo "exit code: $code"
[[ "$code" == "0" ]]
