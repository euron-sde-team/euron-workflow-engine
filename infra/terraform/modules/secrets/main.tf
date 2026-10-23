# Application secrets, generated once and stored in Secrets Manager. ECS injects each
# JSON key into the API and worker containers as an environment variable; the values
# never appear in a task definition, a Terraform plan or a log.
#
# The two are distinct on purpose (production refuses to boot if they are equal):
# rotating the session secret signs everyone out, rotating the pepper invalidates every
# API key, and an operator can do either without the other.
resource "random_password" "this" {
  for_each = toset(["SESSION_SECRET", "API_KEY_PEPPER"])
  length   = 64
  special  = false
}

resource "aws_secretsmanager_secret" "app" {
  #checkov:skip=CKV2_AWS_57:These are HMAC keys; rotation is an operator procedure (docs/guides/operations.md), not a Lambda.
  name                    = "${var.name_prefix}/app"
  description             = "WorkflowEngine session signing secret and API key pepper"
  kms_key_id              = var.kms_key_arn
  recovery_window_in_days = var.recovery_window_in_days
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id     = aws_secretsmanager_secret.app.id
  secret_string = jsonencode({ for k, v in random_password.this : k => v.result })

  # Rotation happens out of band (put a new version by hand or by pipeline). Without
  # this, the next `terraform apply` would quietly roll every secret back.
  lifecycle {
    ignore_changes = [secret_string]
  }
}
