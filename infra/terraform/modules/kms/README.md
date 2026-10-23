# `kms` module

One customer-managed KMS key (annual rotation) plus alias. The deployment creates two: the data key encrypts the workflow data bucket, the queues, RDS, the Valkey cache, Secrets Manager and CloudWatch logs (usage granted per role by IAM, scoped by `kms:ViaService`); the vault key wraps the per-credential data keys of the credentials vault (usage granted per role, scoped by the encryption context).

## Inputs

| Name | Description | Type | Default |
|---|---|---|---|
| `name_prefix` | Prefix for every resource name. | `string` | required |
| `description` | What the key protects, shown in the KMS console. | `string` | `"WorkflowEngine data at rest"` |
| `deletion_window_in_days` | Waiting period before a scheduled key deletion completes. | `number` | `30` |
| `admin_principal_arns` | IAM principals allowed to administer (not use) the key. Empty = account root only, which delegates to IAM policies. | `list(string)` | `[]` |

## Outputs

| Name | Description |
|---|---|
| `key_arn` | KMS key ARN. |
| `key_id` | KMS key id. |
| `alias_name` | Alias, usable as KMS_KEY_ID. |
