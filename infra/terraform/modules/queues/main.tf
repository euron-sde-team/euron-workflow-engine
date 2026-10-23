# Queues that workflows publish to with the SQS node; only these names are on the
# allowlist (SQS_ALLOWED_QUEUES). WorkflowEngine never needs SQS for itself: its own work
# queue is Postgres (docs/architecture/adr/0002-postgres-as-the-queue.md).
#
# Every queue gets a dead-letter queue, so a consumer that keeps failing on a message
# moves it aside after max_receive_count receives instead of retrying it forever. FIFO
# queues (names ending in .fifo) get a FIFO dead-letter queue.
locals {
  managed_sse = var.kms_key_arn == null
  queues = {
    for name in var.names : name => {
      fifo = endswith(name, ".fifo")
      dlq  = endswith(name, ".fifo") ? "${trimsuffix(name, ".fifo")}-dlq.fifo" : "${name}-dlq"
    }
  }
}

resource "aws_sqs_queue" "dlq" {
  for_each                          = local.queues
  name                              = each.value.dlq
  fifo_queue                        = each.value.fifo ? true : null
  message_retention_seconds         = 1209600
  kms_master_key_id                 = var.kms_key_arn
  kms_data_key_reuse_period_seconds = local.managed_sse ? null : 300
  sqs_managed_sse_enabled           = local.managed_sse ? true : null
}

resource "aws_sqs_queue" "this" {
  for_each                          = local.queues
  name                              = each.key
  fifo_queue                        = each.value.fifo ? true : null
  content_based_deduplication       = each.value.fifo ? true : null
  visibility_timeout_seconds        = var.visibility_timeout_seconds
  message_retention_seconds         = var.message_retention_seconds
  receive_wait_time_seconds         = 20
  kms_master_key_id                 = var.kms_key_arn
  kms_data_key_reuse_period_seconds = local.managed_sse ? null : 300
  sqs_managed_sse_enabled           = local.managed_sse ? true : null
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq[each.key].arn
    maxReceiveCount     = var.max_receive_count
  })
}

resource "aws_sqs_queue_redrive_allow_policy" "dlq" {
  for_each  = local.queues
  queue_url = aws_sqs_queue.dlq[each.key].id
  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.this[each.key].arn]
  })
}
