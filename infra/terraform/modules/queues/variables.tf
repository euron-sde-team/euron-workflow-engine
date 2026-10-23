variable "names" {
  description = "Full queue names. A name ending in .fifo creates a FIFO queue; each gets <name>-dlq."
  type        = list(string)
  default     = []
  validation {
    condition     = alltrue([for n in var.names : can(regex("^[A-Za-z0-9_-]{1,75}(\\.fifo)?$", n))])
    error_message = "Queue names use letters, digits, - and _ (at most 75 characters before .fifo)."
  }
}

variable "kms_key_arn" {
  description = "CMK for server-side encryption. Null uses SQS-managed encryption."
  type        = string
  default     = null
}

variable "visibility_timeout_seconds" {
  description = "How long a received message stays hidden from other consumers."
  type        = number
  default     = 60
}

variable "message_retention_seconds" {
  description = "How long an unconsumed message is kept (4 days by default)."
  type        = number
  default     = 345600
}

variable "max_receive_count" {
  description = "Receives before a message moves to the dead-letter queue."
  type        = number
  default     = 5
}
