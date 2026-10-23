# ADR 0005: Branches, merges and loops by token routing with dead-path elimination

## Status

Accepted.

## Context

A visual workflow is a directed graph with conditional branches (`flow.if`,
`flow.switch`), joins (`flow.merge`) and loops (`flow.loop` over batches). The engine must
decide, after every step, which nodes become ready. Two naive rules both fail:

- "Run a node when all its inputs ran" deadlocks a merge after an `if`, because the branch
  that was not taken never reports.
- "Run a node when any input ran" runs a merge once per branch and loses the AND
  semantics a merge exists for.

Loops add scopes: the nodes inside a loop body run once per batch, and the same node id
runs several times in one execution.

## Decision

- Completion of a step emits a token on each outgoing edge: **live** on the ports the
  node took, **dead** on the others. A node that receives only dead tokens is skipped and
  forwards dead tokens in turn (dead-path elimination), so the information "this branch
  will never run" reaches every downstream join.
- A node with one input runs on its first live token. `flow.merge` is an AND join: it
  waits until every input has reported live or dead in the same scope, then runs with the
  live inputs (and is skipped if all were dead). Any other node with several inputs is an
  OR join and runs once per live token.
- `flow.loop` emits one batch at a time into a child scope (`/loop_id:index`). The token
  that returns on the loop's `loop` input advances to the next batch; after the last batch
  the loop takes its `done` port with the collected results. Steps carry their scope, so
  the same node can run once per pass without colliding.
- The routing state (pending joins, arrivals, loop cursors) is a JSON document on the
  execution row, updated in the same transaction as the step that changed it. When the
  execution goes quiet with routing still pending, a flush settles what remains, so a
  graph shape the rules above do not anticipate cannot hang an execution.
- Graph validation on save rejects cycles outside loop bodies, unknown ports, triggers
  with inputs and nodes unreachable from a trigger.

## Consequences

Positive:

- Branch skipping and merges behave the way the diagram suggests, including nested
  branches inside loops.
- Skipped steps are recorded, so the execution view shows which branch did not run and
  why a merge waited.
- The routing core is a pure function of the definition and the completions; the unit
  tests drive it through a simulator without a database.

Trade-offs:

- Every skipped node writes a step row. For very wide graphs with mostly untaken branches
  that is extra rows, which retention prunes with the execution.
- OR joins run once per live input, which surprises people who expected AND semantics;
  the node documentation points them at `flow.merge`.

## Alternatives considered

- **BPMN token semantics with explicit gateway types.** Complete, but asks users to pick
  join kinds for every node; the merge node covers the common case.
- **Topological execution of the whole graph per run.** Simple for straight lines, wrong
  for conditional paths and loops.
