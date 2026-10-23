output "identity_arn" {
  description = "SES identity ARN, for IAM policies."
  value       = aws_sesv2_email_identity.this.arn
}

output "configuration_set_name" {
  description = "SES_CONFIGURATION_SET, or null without one."
  value       = var.create_configuration_set ? aws_sesv2_configuration_set.this[0].configuration_set_name : null
}

output "configuration_set_arn" {
  description = "Configuration set ARN, for IAM policies (null without one)."
  value       = var.create_configuration_set ? aws_sesv2_configuration_set.this[0].arn : null
}

output "dkim_tokens" {
  description = "DKIM tokens of a domain identity; publish <token>._domainkey.<domain> CNAME <token>.dkim.amazonses.com when the zone is not in Route53."
  value       = local.is_domain ? aws_sesv2_email_identity.this.dkim_signing_attributes[0].tokens : []
}
