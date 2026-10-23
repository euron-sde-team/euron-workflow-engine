variable "name_prefix" {
  description = "Prefix for every resource name."
  type        = string
}

variable "alarm_email" {
  description = "Address subscribed to alarm notifications (confirm the e-mail AWS sends). Null: subscribe something else to the topic."
  type        = string
  default     = null
}

variable "alb_arn_suffix" {
  description = "Load balancer ARN suffix."
  type        = string
}

variable "ecs_cluster_name" {
  description = "ECS cluster name."
  type        = string
}

variable "services" {
  description = "Every ECS service to watch for CPU and memory: { api = <service name>, worker = ..., web = ... }."
  type        = map(string)
}

variable "target_groups" {
  description = "Target group ARN suffix per web-facing service, for 5xx and health alarms."
  type        = map(string)
}

variable "worker_service_name" {
  description = "ECS service of the workers, watched for running tasks."
  type        = string
}

variable "dead_letter_queues" {
  description = "Dead-letter queue name by workflow target queue name, for dead-letter alarms."
  type        = map(string)
  default     = {}
}

variable "db_instance_identifier" {
  description = "RDS instance identifier."
  type        = string
}

variable "db_max_connections" {
  description = "Connection ceiling the alarm measures against."
  type        = number
  default     = 200
}
