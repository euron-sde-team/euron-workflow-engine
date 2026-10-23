# Valkey (ElastiCache) for the scheduler leader lock, wake-up and cancel signals, rate
# limits, the webhook secret cache and revoked sessions. Nothing in it is the source of
# truth (Postgres is), so snapshots are optional. It is encrypted at rest with the
# deployment key and in transit with TLS, requires an auth token, and that token reaches
# the tasks only inside REDIS_URL in Secrets Manager.
resource "aws_elasticache_subnet_group" "this" {
  name       = "${var.name_prefix}-cache"
  subnet_ids = var.subnet_ids
}

resource "aws_security_group" "cache" {
  name        = "${var.name_prefix}-cache"
  description = "Valkey; ingress only from application tasks"
  vpc_id      = var.vpc_id
  tags        = { Name = "${var.name_prefix}-cache" }
}

resource "random_password" "auth" {
  length  = 48
  special = false
}

resource "aws_elasticache_replication_group" "this" {
  #checkov:skip=CKV2_AWS_50:Automatic failover needs a replica; it follows cache_replicas (aws-prod runs one, aws-dev none to save cost).
  replication_group_id       = "${var.name_prefix}-cache"
  description                = "Leader lock, signals, rate limits and revoked sessions"
  engine                     = "valkey"
  engine_version             = var.engine_version
  node_type                  = var.node_type
  port                       = 6379
  parameter_group_name       = "default.valkey${split(".", var.engine_version)[0]}"
  num_cache_clusters         = var.replicas + 1
  automatic_failover_enabled = var.replicas > 0
  multi_az_enabled           = var.replicas > 0
  subnet_group_name          = aws_elasticache_subnet_group.this.name
  security_group_ids         = [aws_security_group.cache.id]
  at_rest_encryption_enabled = true
  kms_key_id                 = var.kms_key_arn
  transit_encryption_enabled = true
  auth_token                 = random_password.auth.result
  snapshot_retention_limit   = var.snapshot_retention_days
  auto_minor_version_upgrade = true
  apply_immediately          = var.apply_immediately
}

resource "aws_secretsmanager_secret" "url" {
  #checkov:skip=CKV2_AWS_57:The auth token belongs to the replication group; rotate it by replacing the token (docs/guides/operations.md).
  name                    = "${var.name_prefix}/cache"
  description             = "REDIS_URL for the API and the workers, including the Valkey auth token"
  kms_key_id              = var.kms_key_arn
  recovery_window_in_days = var.recovery_window_in_days
}

resource "aws_secretsmanager_secret_version" "url" {
  secret_id = aws_secretsmanager_secret.url.id
  secret_string = jsonencode({
    REDIS_URL = "rediss://:${random_password.auth.result}@${aws_elasticache_replication_group.this.primary_endpoint_address}:6379/0"
  })
}
