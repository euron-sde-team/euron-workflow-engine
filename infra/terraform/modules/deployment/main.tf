# -----------------------------------------------------------------------------
# One complete WorkflowEngine deployment: network, keys, data, cache and services.
#
#   https://app.<domain>   web app
#   https://api.<domain>   API (interactive reference at /docs) and webhooks (/hooks/...)
#   workers                claim and run steps; one of them is the elected scheduler
#
# envs/aws-dev and envs/aws-prod call this module with different sizes and safety
# switches; everything else is identical by construction.
# -----------------------------------------------------------------------------
data "aws_region" "current" {}

locals {
  region    = data.aws_region.current.region
  hostnames = { app = "app.${var.domain}", api = "api.${var.domain}" }
  urls      = { for k, h in local.hostnames : k => "https://${h}" }
  images    = { for k, url in module.ecr.repository_urls : k => "${url}:${var.image_tag}" }
}

# --- Foundation --------------------------------------------------------------

module "network" {
  source                     = "../network"
  name_prefix                = var.name_prefix
  cidr_block                 = var.vpc_cidr
  az_count                   = var.az_count
  single_nat_gateway         = var.single_nat_gateway
  enable_interface_endpoints = var.enable_interface_endpoints
  flow_log_retention_days    = var.flow_log_retention_days
  logs_kms_key_arn           = module.kms.key_arn
}

# Data at rest: bucket, queues, database, cache, secrets, logs.
module "kms" {
  source                  = "../kms"
  name_prefix             = var.name_prefix
  description             = "${var.name_prefix}: workflow data, queues, database, cache, secrets and logs at rest"
  deletion_window_in_days = var.kms_deletion_window_days
  admin_principal_arns    = var.kms_admin_principal_arns
}

# The credentials vault: wraps one data key per stored credential.
module "vault_key" {
  source                  = "../kms"
  name_prefix             = "${var.name_prefix}-vault"
  description             = "${var.name_prefix}: credentials vault (envelope encryption of workflow credentials)"
  deletion_window_in_days = var.kms_deletion_window_days
  admin_principal_arns    = var.kms_admin_principal_arns
}

module "secrets" {
  source                  = "../secrets"
  name_prefix             = var.name_prefix
  kms_key_arn             = module.kms.key_arn
  recovery_window_in_days = var.secret_recovery_window_days
}

module "database" {
  source                = "../database"
  name_prefix           = var.name_prefix
  vpc_id                = module.network.vpc_id
  subnet_ids            = module.network.private_subnet_ids
  kms_key_arn           = module.kms.key_arn
  instance_class        = var.db_instance_class
  allocated_storage     = var.db_allocated_storage
  max_allocated_storage = var.db_max_allocated_storage
  multi_az              = var.db_multi_az
  backup_retention_days = var.db_backup_retention_days
  deletion_protection   = var.deletion_protection
  skip_final_snapshot   = !var.deletion_protection
  monitoring_interval   = var.db_monitoring_interval
}

module "storage" {
  source            = "../storage"
  name_prefix       = var.name_prefix
  kms_key_arn       = module.kms.key_arn
  enable_versioning = true
  force_destroy     = !var.deletion_protection
}

module "queues" {
  source      = "../queues"
  names       = [for q in var.workflow_queues : "${var.name_prefix}-${q}"]
  kms_key_arn = module.kms.key_arn
}

module "email" {
  source                   = "../email"
  name_prefix              = var.name_prefix
  identity                 = var.mail_identity
  create_configuration_set = true
  route53_zone_id          = var.route53_zone_id
}

module "cache" {
  source                  = "../cache"
  name_prefix             = var.name_prefix
  vpc_id                  = module.network.vpc_id
  subnet_ids              = module.network.private_subnet_ids
  kms_key_arn             = module.kms.key_arn
  node_type               = var.cache_node_type
  replicas                = var.cache_replicas
  apply_immediately       = !var.deletion_protection
  recovery_window_in_days = var.secret_recovery_window_days
}

module "ecr" {
  source       = "../ecr"
  name_prefix  = var.name_prefix
  repositories = ["api", "web"]
  kms_key_arn  = module.kms.key_arn
  force_delete = !var.deletion_protection
}

# --- Edge --------------------------------------------------------------------

module "edge" {
  source              = "../edge"
  name_prefix         = var.name_prefix
  vpc_id              = module.network.vpc_id
  public_subnet_ids   = module.network.public_subnet_ids
  hostnames           = local.hostnames
  route53_zone_id     = var.route53_zone_id
  certificate_arn     = var.certificate_arn
  access_logs_bucket  = var.alb_access_logs_bucket
  enable_waf          = var.enable_waf
  deletion_protection = var.deletion_protection
}

resource "aws_ecs_cluster" "this" {
  name = var.name_prefix
  setting {
    name  = "containerInsights"
    value = "enhanced"
  }
}

# --- Shared application configuration ----------------------------------------

locals {
  app_environment = merge({
    APP_ENV              = "production"
    LOG_FORMAT           = "json"
    PRODUCT_NAME         = var.product_name
    AWS_REGION           = local.region
    CORS_ORIGINS         = local.urls.app
    WEB_URL              = local.urls.app
    API_URL              = local.urls.api
    PUBLIC_HOOKS_URL     = local.urls.api
    COOKIE_SECURE        = "true"
    VAULT_PROVIDER       = "kms"
    KMS_KEY_ID           = module.vault_key.key_arn
    WORKFLOW_DATA_BUCKET = module.storage.bucket_name
    SQS_ALLOWED_QUEUES   = join(",", module.queues.queue_names)
    MAIL_FROM            = var.mail_from
    # No password in the environment: the app reads it from the RDS-managed secret for
    # each new connection, so a rotation needs no redeploy.
    DATABASE_URL        = "postgresql+asyncpg://${module.database.master_username}@${module.database.address}:${module.database.port}/${module.database.database_name}?ssl=require"
    DATABASE_SECRET_ARN = module.database.master_user_secret_arn
    MIGRATE_ON_BOOT     = tostring(var.migrate_on_boot)
    # Trust X-Forwarded-For only from inside the VPC (the load balancer), so per-address
    # limits see the real client and not whatever a client claims to be.
    FORWARDED_ALLOW_IPS = module.network.vpc_cidr_block
    # Workflows may call public endpoints only; list internal hosts here to allow them.
    OUTBOUND_ALLOWED_HOSTS = join(",", var.outbound_allowed_hosts)
    }, module.email.configuration_set_name == null ? {} : {
    SES_CONFIGURATION_SET = module.email.configuration_set_name
  }, var.extra_environment)

  app_secrets = concat(
    [for k in module.secrets.keys : { name = k, valueFrom = "${module.secrets.secret_arn}:${k}::" }],
    [{ name = "REDIS_URL", valueFrom = "${module.cache.url_secret_arn}:REDIS_URL::" }],
  )
}

# What both the API (node test runs, webhooks, manual runs) and the workers (every step)
# do at runtime: read the database password, use the vault key with a credential's
# encryption context, read and write the workflow data bucket, publish to the workflow
# queues and send mail through SES.
data "aws_iam_policy_document" "runtime" {
  statement {
    sid       = "DatabasePassword"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [module.database.master_user_secret_arn]
  }
  statement {
    sid       = "DecryptViaServices"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [module.kms.key_arn]
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values = [
        "s3.${local.region}.amazonaws.com",
        "sqs.${local.region}.amazonaws.com",
        "secretsmanager.${local.region}.amazonaws.com",
      ]
    }
  }
  # Envelope encryption: one data key per credential, bound to its workspace and id.
  statement {
    sid       = "CredentialVault"
    actions   = ["kms:GenerateDataKey", "kms:Decrypt"]
    resources = [module.vault_key.key_arn]
    condition {
      test     = "ForAllValues:StringEquals"
      variable = "kms:EncryptionContextKeys"
      values   = ["workspace_id", "credential_id"]
    }
    condition {
      test     = "Null"
      variable = "kms:EncryptionContext:credential_id"
      values   = ["false"]
    }
  }
  statement {
    sid       = "CredentialVaultHealth"
    actions   = ["kms:DescribeKey"]
    resources = [module.vault_key.key_arn]
  }
  statement {
    sid       = "WorkflowData"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${module.storage.bucket_arn}/*"]
  }
  statement {
    sid       = "WorkflowDataBucket"
    actions   = ["s3:ListBucket"]
    resources = [module.storage.bucket_arn]
  }
  dynamic "statement" {
    for_each = length(var.workflow_queues) > 0 ? [1] : []
    content {
      sid       = "PublishToWorkflowQueues"
      actions   = ["sqs:SendMessage", "sqs:GetQueueUrl", "sqs:GetQueueAttributes"]
      resources = module.queues.queue_arns
    }
  }
  statement {
    sid       = "SendMail"
    actions   = ["ses:SendEmail"]
    resources = compact([module.email.identity_arn, module.email.configuration_set_arn])
  }
}

locals {
  python_health = ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/livez', timeout=3)\""]
  worker_health = ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:9100/metrics', timeout=3)\""]
}

# --- Services ----------------------------------------------------------------

module "api" {
  source                   = "../service"
  name_prefix              = var.name_prefix
  name                     = "api"
  image                    = local.images.api
  environment              = merge(local.app_environment, { SCHEDULER_ENABLED = "false" })
  secrets                  = local.app_secrets
  cluster_arn              = aws_ecs_cluster.this.arn
  vpc_id                   = module.network.vpc_id
  subnet_ids               = module.network.private_subnet_ids
  listener_arn             = module.edge.https_listener_arn
  lb_security_group_id     = module.edge.security_group_id
  listener_priority        = 100
  host_headers             = [local.hostnames.api]
  health_check_path        = "/livez"
  extra_egress_ports       = var.workflow_egress_ports
  connect_to_database      = true
  db_security_group_id     = module.database.security_group_id
  db_port                  = module.database.port
  connect_to_cache         = true
  cache_security_group_id  = module.cache.security_group_id
  kms_key_arn              = module.kms.key_arn
  has_task_policy          = true
  task_policy_json         = data.aws_iam_policy_document.runtime.json
  cpu                      = var.api_cpu
  memory                   = var.api_memory
  min_count                = var.api_min_count
  max_count                = var.api_max_count
  log_retention_days       = var.log_retention_days
  logs_kms_key_arn         = module.kms.key_arn
  container_health_command = local.python_health
}

# Every worker task stands for the scheduler election; one leads at a time
# (docs/architecture/adr/0003-leader-elected-scheduler.md).
module "worker" {
  source                  = "../service"
  name_prefix             = var.name_prefix
  name                    = "worker"
  image                   = local.images.api
  command                 = ["wfe", "worker"]
  environment             = merge(local.app_environment, { WORKER_CONCURRENCY = tostring(var.worker_concurrency), WORKER_METRICS_PORT = "9100", SCHEDULER_ENABLED = "true" })
  secrets                 = local.app_secrets
  attach_to_load_balancer = false
  cluster_arn             = aws_ecs_cluster.this.arn
  vpc_id                  = module.network.vpc_id
  subnet_ids              = module.network.private_subnet_ids
  extra_egress_ports      = var.workflow_egress_ports
  connect_to_database     = true
  db_security_group_id    = module.database.security_group_id
  db_port                 = module.database.port
  connect_to_cache        = true
  cache_security_group_id = module.cache.security_group_id
  kms_key_arn             = module.kms.key_arn
  has_task_policy         = true
  task_policy_json        = data.aws_iam_policy_document.runtime.json
  cpu                     = var.worker_cpu
  memory                  = var.worker_memory
  min_count               = var.worker_min_count
  max_count               = var.worker_max_count
  log_retention_days      = var.log_retention_days
  logs_kms_key_arn        = module.kms.key_arn
  # A worker serves no traffic; the container check reads its metrics endpoint.
  container_health_command = local.worker_health
}

# One-off tasks on the API image: migrations and accounts (make aws-cli).
module "cli" {
  source                  = "../service"
  name_prefix             = var.name_prefix
  name                    = "cli"
  image                   = local.images.api
  command                 = ["wfe", "--help"]
  environment             = local.app_environment
  secrets                 = local.app_secrets
  create_service          = false
  cluster_arn             = aws_ecs_cluster.this.arn
  vpc_id                  = module.network.vpc_id
  subnet_ids              = module.network.private_subnet_ids
  connect_to_database     = true
  db_security_group_id    = module.database.security_group_id
  db_port                 = module.database.port
  connect_to_cache        = true
  cache_security_group_id = module.cache.security_group_id
  kms_key_arn             = module.kms.key_arn
  has_task_policy         = true
  task_policy_json        = data.aws_iam_policy_document.runtime.json
  cpu                     = 512
  memory                  = 1024
  log_retention_days      = var.log_retention_days
  logs_kms_key_arn        = module.kms.key_arn
}

module "web" {
  source               = "../service"
  name_prefix          = var.name_prefix
  name                 = "web"
  image                = local.images.web
  environment          = { API_URL = local.urls.api, PRODUCT_NAME = var.product_name, PORT = "8080", HOSTNAME = "0.0.0.0" }
  cluster_arn          = aws_ecs_cluster.this.arn
  vpc_id               = module.network.vpc_id
  subnet_ids           = module.network.private_subnet_ids
  listener_arn         = module.edge.https_listener_arn
  lb_security_group_id = module.edge.security_group_id
  listener_priority    = 110
  host_headers         = [local.hostnames.app]
  health_check_path    = "/env.js"
  kms_key_arn          = module.kms.key_arn
  cpu                  = var.web_cpu
  memory               = var.web_memory
  min_count            = var.web_min_count
  max_count            = var.web_max_count
  log_retention_days   = var.log_retention_days
  logs_kms_key_arn     = module.kms.key_arn
}

# --- Observability -----------------------------------------------------------

module "observability" {
  source                 = "../observability"
  name_prefix            = var.name_prefix
  alarm_email            = var.alarm_email
  alb_arn_suffix         = module.edge.arn_suffix
  ecs_cluster_name       = aws_ecs_cluster.this.name
  db_instance_identifier = module.database.instance_identifier
  worker_service_name    = module.worker.service_name
  dead_letter_queues     = module.queues.dlq_names
  services = {
    api    = module.api.service_name
    worker = module.worker.service_name
    web    = module.web.service_name
  }
  target_groups = {
    api = module.api.target_group_arn_suffix
    web = module.web.target_group_arn_suffix
  }
}
