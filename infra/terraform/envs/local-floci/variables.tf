variable "endpoint" {
  description = "Emulator endpoint. http://localhost:4613 from the host, http://floci:4566 inside compose."
  type        = string
  default     = "http://localhost:4613"
}

variable "name_prefix" {
  description = "Must match KMS_KEY_ID and WORKFLOW_DATA_BUCKET in deploy/compose/compose.floci.yaml."
  type        = string
  default     = "wfe-local"
}

variable "workflow_queues" {
  description = "Must match SQS_ALLOWED_QUEUES in deploy/compose/compose.floci.yaml."
  type        = list(string)
  default     = ["order-events"]
}

variable "mail_identity" {
  description = "Must match the address in MAIL_FROM in deploy/compose/compose.floci.yaml."
  type        = string
  default     = "automations@wfe.example.test"
}
