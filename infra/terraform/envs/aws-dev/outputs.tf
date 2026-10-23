output "urls" {
  description = "Public URLs of the web app and the API."
  value       = module.wfe.urls
}

output "ecr_repository_urls" {
  description = "Image repositories."
  value       = module.wfe.ecr_repository_urls
}

output "cluster_name" {
  description = "ECS cluster."
  value       = module.wfe.cluster_name
}

output "service_names" {
  description = "ECS services."
  value       = module.wfe.service_names
}

output "cli_task_definition" {
  description = "Task definition for one-off CLI tasks."
  value       = module.wfe.cli_task_definition
}

output "cli_security_group_id" {
  description = "Security group for one-off CLI tasks."
  value       = module.wfe.cli_security_group_id
}

output "private_subnet_ids" {
  description = "Private subnets for one-off tasks."
  value       = module.wfe.private_subnet_ids
}

output "load_balancer_dns_name" {
  description = "Point app.<domain> and api.<domain> here when the zone is not in Route53."
  value       = module.wfe.load_balancer_dns_name
}

output "certificate_validation_records" {
  description = "DNS records to publish when the zone is not in Route53."
  value       = module.wfe.certificate_validation_records
}

output "workflow_data_bucket" {
  description = "WORKFLOW_DATA_BUCKET, the default bucket of the S3 nodes."
  value       = module.wfe.workflow_data_bucket
}

output "vault_key_alias" {
  description = "KMS key of the credentials vault."
  value       = module.wfe.vault_key_alias
}

output "workflow_queue_urls" {
  description = "Queues workflows may publish to."
  value       = module.wfe.workflow_queue_urls
}

output "mail_dkim_tokens" {
  description = "DKIM tokens to publish when the mail domain is not in Route53."
  value       = module.wfe.mail_dkim_tokens
}
