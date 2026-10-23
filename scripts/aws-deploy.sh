#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# One-shot deployment to AWS:  scripts/aws-deploy.sh <aws-dev|aws-prod> <image-tag>
#
#   1. terraform apply the image registries (and the KMS key that encrypts them)
#   2. build the api and web images for linux/arm64 and push them
#   3. terraform apply everything else with that image tag
#   4. wait for the api, worker and web services to become stable
#
# Needs: terraform, docker (buildx), the AWS CLI, credentials for the target account,
# and infra/terraform/envs/<env>/terraform.tfvars (copy the .example next to it).
# Migrations run when the API boots (MIGRATE_ON_BOOT, advisory-locked).
# -----------------------------------------------------------------------------
set -euo pipefail
ENV="${1:?usage: aws-deploy.sh <aws-dev|aws-prod> <image-tag>}"
TAG="${2:?usage: aws-deploy.sh <aws-dev|aws-prod> <image-tag>}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIR="$ROOT/infra/terraform/envs/$ENV"

for bin in terraform docker aws; do command -v "$bin" >/dev/null || { echo "missing: $bin"; exit 1; }; done
[[ -f "$DIR/terraform.tfvars" ]] || { echo "create $DIR/terraform.tfvars from terraform.tfvars.example first"; exit 1; }
[[ -n "$(git -C "$ROOT" status --porcelain 2>/dev/null)" ]] && echo "note: the working tree has uncommitted changes; the images are built from it as-is"

tf() { terraform -chdir="$DIR" "$@"; }

echo "==> terraform init"
tf init -input=false >/dev/null

echo "==> 1/4 registries"
tf apply -input=false -auto-approve -var "image_tag=$TAG" -target=module.wfe.module.ecr

region=$(aws configure get region 2>/dev/null || true)
region="${AWS_REGION:-${region:-$(grep -E '^region' "$DIR/terraform.tfvars" | sed -E 's/.*"(.*)".*/\1/')}}"
repos_json=$(tf output -json ecr_repository_urls)
registry=$(echo "$repos_json" | sed -E 's#.*"api": *"([^/]+)/.*#\1#')
aws ecr get-login-password --region "$region" | docker login --username AWS --password-stdin "$registry" >/dev/null

echo "==> 2/4 images ($TAG, linux/arm64)"
for app in api web; do
  repo=$(echo "$repos_json" | sed -E "s#.*\"$app\": *\"([^\"]+)\".*#\1#")
  docker buildx build --platform linux/arm64 -f "$ROOT/infra/docker/$app.Dockerfile" -t "$repo:$TAG" --push "$ROOT"
done

echo "==> 3/4 infrastructure"
tf apply -input=false -auto-approve -var "image_tag=$TAG"

echo "==> 4/4 waiting for the services"
cluster=$(tf output -raw cluster_name)
services=$(tf output -json service_names | python3 -c "import json,sys; print(' '.join(json.load(sys.stdin).values()))")
# shellcheck disable=SC2086 # one argument per service name
aws ecs wait services-stable --region "$region" --cluster "$cluster" --services $services

echo
tf output urls
cat <<NEXT

Deployed $TAG to $ENV. Next:
  make aws-cli ENV=$ENV ARGS="user create --email you@example.com --name 'You' --admin"
  then sign in on the app URL above and create a workspace.
NEXT
