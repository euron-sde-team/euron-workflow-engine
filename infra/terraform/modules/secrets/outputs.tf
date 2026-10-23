output "secret_arn" {
  description = "ARN of the JSON secret holding SESSION_SECRET and API_KEY_PEPPER."
  value       = aws_secretsmanager_secret.app.arn
}

output "keys" {
  description = "JSON keys inside the secret, for ECS `secrets` valueFrom references."
  value       = sort(keys(random_password.this))
}
