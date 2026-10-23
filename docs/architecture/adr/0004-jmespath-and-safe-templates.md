# ADR 0004: JMESPath and logic-free templates instead of a code node

## Status

Accepted.

## Context

Workflows constantly reshape data: pick fields out of a webhook body, build a request
body from earlier steps, filter a list of rows, compare a total against a threshold. Most
automation tools solve this with a "code" node that runs JavaScript or Python. Running
editor-supplied code inside the worker means a sandbox that must hold against a motivated
user with network access, credentials in scope and the database on the same host. Every
popular sandbox has a history of escapes.

## Decision

- Data selection and reshaping use **JMESPath** (a specified, side-effect-free query
  language with a conformance suite), compiled once per expression and evaluated over the
  context `{trigger, input, steps, vars, env, execution}`. A small set of custom functions
  covers what JMESPath lacks: strings (`upper`, `split`, `replace`, `url_encode`,
  `base64_encode`), numbers (`round`, `format_number`), dates (`now`, `format_date`,
  `date_add`), collections (`unique`, `group_by`), JSON (`to_json`, `from_json`), hashing
  (`sha256`) and `default` for missing values.
- String building uses **templates**: `{{ steps.fetch.body.id }}` placeholders inside
  JSON values, where each placeholder is a JMESPath expression. A value that is exactly
  one placeholder keeps its type (a number stays a number); anything else is rendered to
  a string. There are no loops, no conditionals and no function definitions in templates.
- Branching uses the `flow.if` and `flow.switch` nodes with typed conditions (equals,
  greater than, contains, is empty, ...) evaluated over JMESPath values. There is no regex
  operator, so no catastrophic backtracking on user input.
- Expressions and templates are validated when a draft is saved, so syntax errors are
  shown on the node before a run.

## Consequences

Positive:

- Nothing an editor writes can execute code, open a socket or read a file. The attack
  surface of a workflow is the node catalog, each node with its own allowlists and limits.
- Expressions are deterministic and cheap, and the editor can test one node in isolation.
- Exported workflows stay portable data, not programs.

Trade-offs:

- Some transformations take two nodes where a code node would take one line, and JMESPath
  has a learning curve. The gallery templates and the node descriptions show the common
  patterns.
- Arithmetic is limited to what JMESPath and the custom functions provide.

## Alternatives considered

- **A JavaScript or Python code node in a sandbox** (subprocess, WebAssembly, V8
  isolates). Flexible, but the sandbox becomes the most security-critical component in the
  product and needs constant hardening.
- **Jinja2 templates.** Familiar, but a Turing-complete template language with a history
  of sandbox escapes; JMESPath placeholders give the useful part without that.
- **JSONata.** Expressive, but its only maintained implementation is JavaScript.
