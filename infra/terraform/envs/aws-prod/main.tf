# -----------------------------------------------------------------------------
# aws-prod: production. Three zones, NAT per zone, Multi-AZ database, cache failover,
# WAF, deletion protection and a year of logs.
#
# Everything is in ../../modules/deployment; this file only picks the sizes.
#   make aws-deploy ENV=aws-prod
# -----------------------------------------------------------------------------
module "wfe" {
  source = "../../modules/deployment"

  name_prefix     = var.name_prefix
  domain          = var.domain
  route53_zone_id = var.route53_zone_id
  certificate_arn = var.certificate_arn
  product_name    = var.product_name
  image_tag       = var.image_tag

  mail_identity          = var.mail_identity
  mail_from              = var.mail_from
  workflow_queues        = var.workflow_queues
  workflow_egress_ports  = var.workflow_egress_ports
  outbound_allowed_hosts = var.outbound_allowed_hosts

  az_count                   = 3
  single_nat_gateway         = false
  enable_interface_endpoints = true

  db_instance_class        = var.db_instance_class
  db_multi_az              = true
  db_backup_retention_days = 14
  deletion_protection      = true

  cache_node_type = var.cache_node_type
  cache_replicas  = 1

  enable_waf = true

  kms_deletion_window_days    = 30
  secret_recovery_window_days = 30

  api_min_count    = 2
  api_max_count    = 6
  worker_min_count = 2
  worker_max_count = 8
  web_min_count    = 2
  web_max_count    = 6

  log_retention_days = 365
  alarm_email        = var.alarm_email
}
