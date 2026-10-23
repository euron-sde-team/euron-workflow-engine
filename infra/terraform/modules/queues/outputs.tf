output "queue_names" {
  description = "Queue names, for SQS_ALLOWED_QUEUES."
  value       = [for q in aws_sqs_queue.this : q.name]
}

output "queue_urls" {
  description = "Queue URL by name."
  value       = { for name, q in aws_sqs_queue.this : name => q.url }
}

output "queue_arns" {
  description = "Queue ARNs, for IAM policies."
  value       = [for q in aws_sqs_queue.this : q.arn]
}

output "dlq_names" {
  description = "Dead-letter queue name by queue name, for CloudWatch alarms."
  value       = { for name, q in aws_sqs_queue.dlq : name => q.name }
}
