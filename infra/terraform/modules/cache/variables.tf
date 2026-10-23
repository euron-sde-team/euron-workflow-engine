variable "name_prefix" {
  description = "Prefix for every resource name."
  type        = string
}

variable "vpc_id" {
  description = "VPC the cache lives in."
  type        = string
}

variable "subnet_ids" {
  description = "Private subnets for the cache nodes."
  type        = list(string)
}

variable "kms_key_arn" {
  description = "CMK for encryption at rest and for the REDIS_URL secret."
  type        = string
}

variable "engine_version" {
  description = "Valkey engine version."
  type        = string
  default     = "8.0"
}

variable "node_type" {
  description = "ElastiCache node type."
  type        = string
  default     = "cache.t4g.small"
}

variable "replicas" {
  description = "Read replicas; one or more enables automatic failover across availability zones."
  type        = number
  default     = 0
}

variable "snapshot_retention_days" {
  description = "Daily snapshots kept. The cache is rebuildable, so 0 (none) is a reasonable default."
  type        = number
  default     = 0
}

variable "apply_immediately" {
  description = "Apply modifications now instead of in the maintenance window."
  type        = bool
  default     = false
}

variable "recovery_window_in_days" {
  description = "Secrets Manager recovery window for the REDIS_URL secret (0 deletes immediately)."
  type        = number
  default     = 7
}
