# ADR 0007: An editable draft and immutable published versions

## Status

Accepted.

## Context

People edit workflows while they run in production. A webhook that arrives while someone
is halfway through rewiring a branch must not run the half-edited graph, and an
execution that started yesterday must finish with the definition it started with, even
after three new releases. Operators also need to know which version produced a given
execution, and to go back.

## Decision

- A workflow has one **draft** (`workflows.draft`, autosaved by the editor with an
  optimistic `draft_revision`, so two editors cannot silently overwrite each other) and
  any number of **published versions** (`workflow_versions`, numbered 1, 2, 3...).
- Publishing validates the draft and copies it into a new version row. A database trigger
  makes published versions immutable.
- Triggers (webhooks, schedules, event subscriptions) are indexed from the **published**
  version of an **active** workflow only. Publishing an active workflow swaps the index
  to the new version in the same transaction.
- Every execution records the version it runs. Test runs from the editor run the draft:
  the draft is snapshotted into an unnumbered version (deduplicated by checksum) and the
  execution is marked `mode = test`.
- Restoring a version copies it into the draft; it does not rewrite history.
- Export produces a portable JSON document with credentials referenced by name and type;
  import resolves them against the target workspace and reports the ones that are missing.

## Consequences

Positive:

- In-flight executions are never affected by edits or later releases; resume from a
  failed step uses the version the execution started with.
- The execution view always draws the graph that actually ran.
- Rollback is "restore version N, publish".

Trade-offs:

- Draft snapshots for test runs add version rows. They are deduplicated by checksum (a
  test run of an unchanged draft reuses the last snapshot) and are deleted with the
  workflow; they are not pruned with old executions.
- A fix to a failed execution's workflow does not apply to a resume of that execution;
  the operator retries from the start (which uses the current version) when that is what
  they want. The UI offers both.

## Alternatives considered

- **Edit in place with a "paused" flag.** Simpler, but every edit risks in-flight runs and
  history loses the graph that produced it.
- **Git-style branches.** More power than a workflow tool needs; a draft plus versions
  covers review-then-release.
