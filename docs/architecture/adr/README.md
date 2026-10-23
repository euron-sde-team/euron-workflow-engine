# Architecture decision records

Each record states one decision, the context that forced it, what it costs, and the
alternatives that were weighed. Records are immutable once accepted: a later decision that
changes course gets a new record that supersedes the old one.

| ADR | Decision | Status |
| --- | --- | --- |
| [0001](0001-one-image-three-roles.md) | One image for the API, the workers and the scheduler | Accepted |
| [0002](0002-postgres-as-the-queue.md) | Postgres is the work queue (`FOR UPDATE SKIP LOCKED`, guarded writes) | Accepted |
| [0003](0003-leader-elected-scheduler.md) | A leader-elected scheduler that stays correct without its lock | Accepted |
| [0004](0004-jmespath-and-safe-templates.md) | JMESPath and logic-free templates instead of a code node | Accepted |
| [0005](0005-dead-path-elimination.md) | Branches, merges and loops by token routing with dead-path elimination | Accepted |
| [0006](0006-kms-envelope-encryption.md) | Credentials envelope-encrypted with per-credential KMS data keys | Accepted |
| [0007](0007-draft-and-published-versions.md) | An editable draft and immutable published versions | Accepted |
| [0008](0008-floci-for-local-aws.md) | Develop against the Floci AWS emulator, provisioned by the production Terraform | Accepted |
| [0009](0009-workspaces-as-the-tenant-boundary.md) | Workspaces are the tenant boundary inside one deployment | Accepted |

Template for a new record: Status, Context, Decision, Consequences (positive and
trade-offs), Alternatives considered.
