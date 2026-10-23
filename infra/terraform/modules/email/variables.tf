variable "name_prefix" {
  description = "Prefix for every resource name."
  type        = string
}

variable "identity" {
  description = "Domain (example.com) or address (automations@example.com) the email node sends from."
  type        = string
}

variable "create_configuration_set" {
  description = "Create a configuration set (TLS required, reputation metrics, bounce and complaint suppression)."
  type        = bool
  default     = true
}

variable "route53_zone_id" {
  description = "Hosted zone of a domain identity, to publish its DKIM records. Null: publish them yourself."
  type        = string
  default     = null
}
