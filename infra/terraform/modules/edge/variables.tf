variable "name_prefix" {
  description = "Prefix for every resource name."
  type        = string
}

variable "vpc_id" {
  description = "VPC for the load balancer."
  type        = string
}

variable "public_subnet_ids" {
  description = "Public subnets, one per AZ."
  type        = list(string)
}

variable "hostnames" {
  description = "Host name per application: { app = \"app.example.com\", api = \"api.example.com\" }."
  type        = map(string)
}

variable "route53_zone_id" {
  description = "Hosted zone for the host names. When set, the certificate is validated and records are created automatically."
  type        = string
  default     = null
}

variable "certificate_arn" {
  description = "Existing ACM certificate covering every host name. Null requests a new one."
  type        = string
  default     = null
}

variable "access_logs_bucket" {
  description = "Bucket for ALB access logs. Null disables them."
  type        = string
  default     = null
}

variable "enable_waf" {
  description = "Put a WAF (AWS managed rules plus a per-IP rate limit) in front of the load balancer."
  type        = bool
  default     = false
}

variable "waf_rate_limit" {
  description = "Requests per 5 minutes from one IP before the WAF blocks it."
  type        = number
  default     = 2000
}

variable "deletion_protection" {
  description = "Protect the load balancer from deletion."
  type        = bool
  default     = false
}
