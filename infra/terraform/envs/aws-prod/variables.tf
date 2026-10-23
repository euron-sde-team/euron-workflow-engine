variable "region" {
  description = "AWS region."
  type        = string
  default     = "us-east-1"
}

variable "name_prefix" {
  description = "Prefix for every resource name."
  type        = string
  default     = "wfe-prod"
}

variable "domain" {
  description = "Parent domain: the app is served at app.<domain> and the API at api.<domain>."
  type        = string
}

variable "route53_zone_id" {
  description = "Hosted zone for the domain. Null: publish the DNS records from the outputs yourself."
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

variable "image_tag" {
  description = "Image tag to deploy (make aws-deploy passes the git commit)."
  type        = string
  default     = "latest"
}

variable "db_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.r7g.large"
}

variable "cache_node_type" {
  description = "ElastiCache node type."
  type        = string
  default     = "cache.r7g.large"
}

variable "alarm_email" {
  description = "Address that receives alarm notifications."
  type        = string
  default     = null
}

variable "mail_identity" {
  description = "SES identity the email node sends from: a domain (recommended) or an address."
  type        = string
}

variable "mail_from" {
  description = "MAIL_FROM, an address on mail_identity, e.g. \"Automations <automations@example.com>\"."
  type        = string
}

variable "workflow_queues" {
  description = "SQS queues workflows may publish to, created as <name_prefix>-<name>."
  type        = list(string)
  default     = ["events"]
}

variable "workflow_egress_ports" {
  description = "TCP ports besides 443 that workflow steps may reach on the internet."
  type        = list(number)
  default     = [80]
}

variable "outbound_allowed_hosts" {
  description = "Internal host names workflows may reach despite the private-network block."
  type        = list(string)
  default     = []
}
