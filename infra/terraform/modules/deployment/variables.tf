variable "name_prefix" {
  description = "Prefix for every resource name; one AWS account can host several deployments."
  type        = string
}

variable "domain" {
  description = "Parent domain. The web app is served at app.<domain> and the API at api.<domain>."
  type        = string
}

variable "route53_zone_id" {
  description = "Hosted zone for the domain. When set, the certificate and DNS records are created automatically."
  type        = string
  default     = null
}

variable "certificate_arn" {
  description = "Existing ACM certificate for app.<domain> and api.<domain>. Null requests one."
  type        = string
  default     = null
}

variable "product_name" {
  description = "Name shown in the web app."
  type        = string
  default     = "Euron WorkflowEngine"
}

variable "mail_identity" {
  description = "SES identity the email node sends from: a domain (recommended) or an address."
  type        = string
}

variable "mail_from" {
  description = "MAIL_FROM header, on the mail identity, e.g. \"Automations <automations@example.com>\"."
  type        = string
}

variable "workflow_queues" {
  description = "SQS queues workflows may publish to, created as <name_prefix>-<name> with a dead-letter queue each."
  type        = list(string)
  default     = ["events"]
}

variable "workflow_egress_ports" {
  description = "TCP ports besides 443 that workflow steps may reach on the internet (80 for plain HTTP APIs, 5432 for external Postgres)."
  type        = list(number)
  default     = [80]
}

variable "outbound_allowed_hosts" {
  description = "Internal host names workflows may reach despite the private-network block (OUTBOUND_ALLOWED_HOSTS)."
  type        = list(string)
  default     = []
}

variable "image_tag" {
  description = "Image tag deployed for the api and web repositories (the git commit by default)."
  type        = string
}

variable "migrate_on_boot" {
  description = "Run pending migrations when an API task starts (under an advisory lock)."
  type        = bool
  default     = true
}

variable "vpc_cidr" {
  description = "VPC address range."
  type        = string
  default     = "10.43.0.0/16"
}

variable "az_count" {
  description = "Availability zones to spread across."
  type        = number
  default     = 2
}

variable "single_nat_gateway" {
  description = "One NAT gateway for all zones (cheaper, less available)."
  type        = bool
  default     = true
}

variable "enable_interface_endpoints" {
  description = "Interface VPC endpoints for AWS APIs (keeps that traffic off the NAT)."
  type        = bool
  default     = false
}

variable "flow_log_retention_days" {
  description = "VPC flow log retention."
  type        = number
  default     = 30
}

variable "kms_deletion_window_days" {
  description = "Waiting period before the deployment key can be deleted."
  type        = number
  default     = 30
}

variable "kms_admin_principal_arns" {
  description = "IAM principals allowed to administer the deployment key."
  type        = list(string)
  default     = []
}

variable "secret_recovery_window_days" {
  description = "Secrets Manager recovery window (0 deletes immediately)."
  type        = number
  default     = 7
}

variable "db_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t4g.medium"
}

variable "db_allocated_storage" {
  description = "Initial database storage in GiB."
  type        = number
  default     = 30
}

variable "db_max_allocated_storage" {
  description = "Storage autoscaling ceiling in GiB."
  type        = number
  default     = 200
}

variable "db_multi_az" {
  description = "Standby replica in a second zone."
  type        = bool
  default     = false
}

variable "db_backup_retention_days" {
  description = "Automated backup retention."
  type        = number
  default     = 7
}

variable "db_monitoring_interval" {
  description = "Enhanced monitoring interval in seconds (0 disables it)."
  type        = number
  default     = 60
}

variable "cache_node_type" {
  description = "ElastiCache node type for Valkey."
  type        = string
  default     = "cache.t4g.small"
}

variable "cache_replicas" {
  description = "Valkey read replicas; one or more enables automatic failover."
  type        = number
  default     = 0
}

variable "deletion_protection" {
  description = "Protect the database, bucket, load balancer and registries from deletion."
  type        = bool
  default     = false
}

variable "enable_waf" {
  description = "Put a WAF in front of the load balancer."
  type        = bool
  default     = false
}

variable "alb_access_logs_bucket" {
  description = "Bucket for load balancer access logs. Null disables them."
  type        = string
  default     = null
}

variable "api_cpu" {
  description = "API task CPU units."
  type        = number
  default     = 512
}

variable "api_memory" {
  description = "API task memory (MiB)."
  type        = number
  default     = 1024
}

variable "api_min_count" {
  description = "Minimum API tasks."
  type        = number
  default     = 1
}

variable "api_max_count" {
  description = "Maximum API tasks."
  type        = number
  default     = 2
}

variable "worker_cpu" {
  description = "Worker task CPU units."
  type        = number
  default     = 512
}

variable "worker_memory" {
  description = "Worker task memory (MiB)."
  type        = number
  default     = 1024
}

variable "worker_concurrency" {
  description = "Steps a worker task runs at once (WORKER_CONCURRENCY)."
  type        = number
  default     = 8
}

variable "worker_min_count" {
  description = "Minimum worker tasks."
  type        = number
  default     = 1
}

variable "worker_max_count" {
  description = "Maximum worker tasks."
  type        = number
  default     = 2
}

variable "web_cpu" {
  description = "Web task CPU units."
  type        = number
  default     = 256
}

variable "web_memory" {
  description = "Web task memory (MiB)."
  type        = number
  default     = 512
}

variable "web_min_count" {
  description = "Minimum web tasks."
  type        = number
  default     = 1
}

variable "web_max_count" {
  description = "Maximum web tasks."
  type        = number
  default     = 2
}

variable "log_retention_days" {
  description = "CloudWatch log retention for every service."
  type        = number
  default     = 30
}

variable "alarm_email" {
  description = "Address that receives alarm notifications. Null: subscribe something else to the topic."
  type        = string
  default     = null
}

variable "extra_environment" {
  description = "Additional environment variables for the API and the workers."
  type        = map(string)
  default     = {}
}
