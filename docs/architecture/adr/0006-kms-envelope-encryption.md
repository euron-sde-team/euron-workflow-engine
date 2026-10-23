# ADR 0006: Credentials envelope-encrypted with per-credential KMS data keys

## Status

Accepted.

## Context

Workflows call authenticated APIs, databases and Slack with credentials an editor stores
once: bearer tokens, basic auth, API key headers, webhook signing secrets, database
passwords. They are the most valuable data in the product. They must be usable by the
workers at run time, never returned by the API, never written to logs or step output,
and a database dump alone must not reveal them.

## Decision

- Each credential has a JSON schema (per credential type) that marks its secret fields.
  Public fields (a username, a host) are stored in clear; the whole value is sealed.
- Sealing: KMS `GenerateDataKey` (AES-256) on the **vault key** with the encryption
  context `{workspace_id, credential_id}`; the value is encrypted with AES-256-GCM under
  the plaintext data key, with the same context as associated data; the row stores the
  ciphertext, the nonce, the wrapped data key and the key reference. The plaintext key is
  dropped immediately.
- Opening: KMS `Decrypt` of the wrapped key with the same context, then AES-GCM open.
  A row copied to another workspace or another credential id fails both checks.
- The vault key is separate from the deployment's data key, and the task roles may use it
  only with that encryption context (IAM condition on `kms:EncryptionContextKeys`), so the
  key cannot be used as a general-purpose encryption oracle.
- The API returns only the name, type, public fields, the names of the secret fields and
  metadata. Updating with a blank secret keeps the stored value, so an edit form never
  needs the secret.
- At run time a node receives decrypted values only for the credentials its own config
  references, and every secret value is redacted (`[redacted]`) from step output, log
  lines and errors before they are stored.
- Without KMS (`VAULT_PROVIDER=local`, laptops without the emulator) the same format is
  used with a key derived from `VAULT_LOCAL_KEY`; production refuses to start without KMS.

## Consequences

Positive:

- A leaked database dump, backup or snapshot does not expose credentials without KMS
  access, and KMS access is logged in CloudTrail.
- Rotating the vault key (annual, automatic) needs no re-encryption: old data keys stay
  decryptable through the key's previous material.
- The same code path runs locally against Floci, so the encryption context handling is
  tested on every `make up`.

Trade-offs:

- Every credential use costs one KMS `Decrypt` call (latency and per-request price).
  Plaintext data keys are not cached across steps, by choice.
- Value-based redaction can miss a secret that a remote service transforms (for example
  echoes base64-encoded); the threat model lists this.

## Alternatives considered

- **One application key in an environment variable.** Simple, but a leaked task
  definition or process dump exposes every credential at once.
- **AWS Secrets Manager per credential.** Strong, but one secret per user credential means
  per-secret charges, API throttling on bulk runs, and secrets created by user action
  outside Terraform's view.
- **HashiCorp Vault Transit.** Equivalent model, another cluster to run.
