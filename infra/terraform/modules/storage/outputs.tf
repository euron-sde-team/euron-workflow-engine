output "bucket_name" {
  description = "Workflow data bucket name (WORKFLOW_DATA_BUCKET)."
  value       = aws_s3_bucket.data.bucket
}

output "bucket_arn" {
  description = "Workflow data bucket ARN, for IAM policies."
  value       = aws_s3_bucket.data.arn
}
