# -----------------------------------------------------------------------------
# Local environment on the Floci AWS emulator.
#
# The modules that build AWS run here unchanged; only the provider endpoints differ.
# `make up` applies this automatically (the compose `terraform` one-shot) before the
# migrations, the API and the workers start, so local workflows encrypt credentials with
# KMS, write to S3 with SSE-KMS, publish to SQS and send mail through SES exactly as on
# AWS. By hand, against a running emulator:
#
#   terraform -chdir=infra/terraform/envs/local-floci init
#   terraform -chdir=infra/terraform/envs/local-floci apply
# -----------------------------------------------------------------------------

module "kms" {
  source                  = "../../modules/kms"
  name_prefix             = var.name_prefix
  description             = "${var.name_prefix}: workflow data and secrets at rest"
  deletion_window_in_days = 7
}

module "vault_key" {
  source                  = "../../modules/kms"
  name_prefix             = "${var.name_prefix}-vault"
  description             = "${var.name_prefix}: credentials vault"
  deletion_window_in_days = 7
}

module "storage" {
  source            = "../../modules/storage"
  name_prefix       = var.name_prefix
  kms_key_arn       = module.kms.key_arn
  enforce_tls       = false # the emulator speaks plain HTTP
  enable_versioning = false
  force_destroy     = true
}

# The demo templates publish to order-events, so the local queue keeps that exact name.
module "queues" {
  source      = "../../modules/queues"
  names       = var.workflow_queues
  kms_key_arn = module.kms.key_arn
}

module "email" {
  source                   = "../../modules/email"
  name_prefix              = var.name_prefix
  identity                 = var.mail_identity
  create_configuration_set = false
}

# Generated secrets are an AWS-deployment concern; locally compose reads
# deploy/compose/.env (make env). Created here anyway so the module is exercised.
module "secrets" {
  source                  = "../../modules/secrets"
  name_prefix             = var.name_prefix
  kms_key_arn             = module.kms.key_arn
  recovery_window_in_days = 0
}
