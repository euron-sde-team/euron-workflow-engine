output "security_group_id" {
  description = "Security group of the cache; services add their own ingress rules to it."
  value       = aws_security_group.cache.id
}

output "port" {
  description = "Valkey port."
  value       = 6379
}

output "url_secret_arn" {
  description = "Secret holding REDIS_URL (JSON key REDIS_URL)."
  value       = aws_secretsmanager_secret.url.arn
}

output "primary_endpoint" {
  description = "Primary endpoint address."
  value       = aws_elasticache_replication_group.this.primary_endpoint_address
}
