output "vault_key_alias" {
  description = "KMS_KEY_ID for the local stack."
  value       = module.vault_key.alias_name
}

output "workflow_data_bucket" {
  description = "WORKFLOW_DATA_BUCKET for the local stack."
  value       = module.storage.bucket_name
}

output "workflow_queue_urls" {
  description = "Queues local workflows may publish to (SQS_ALLOWED_QUEUES)."
  value       = module.queues.queue_urls
}

output "mail_identity_arn" {
  description = "The SES identity behind MAIL_FROM."
  value       = module.email.identity_arn
}
