# Walkthrough: from a paid order to a resumed failure

This walkthrough follows one realistic automation through the product, using the demo
workspace (`make up && make demo`, then sign in as `maya@northwind.example.com`). Each step
names the screen and what happens underneath.

## 0. The workspace

Northwind Outfitters sells outdoor gear. Its workspace holds seven workflows built from the
templates gallery, seven credentials (webhook secrets, Slack channels, a read-only warehouse
database), nine variables (the URLs of the shop, fulfillment, CRM, billing and status APIs,
team email addresses) and two weeks of executions that really ran.

## 1. The workflow

**Workflows, then *Ship paid orders from the shop*.** The editor shows the graph:

```text
Paid order (signed webhook)
  -> Normalize order (Transform)
       -> Large order? (If) --true--> Tell sales (Slack)
       -> Create shipment (HTTP, retried) -> Archive to S3 -> Publish order event (SQS)
```

- The trigger is a webhook at `/hooks/northwind/shop/orders`, verified with HMAC-SHA256
  over the raw body (header `X-Shop-Signature`), and deduplicated by `Idempotency-Key`.
- *Normalize order* reshapes the body with a JMESPath expression; nothing an editor writes
  can execute code.
- *Large order?* and *Create shipment* both follow *Normalize order*: the sales alert is a
  side branch that runs only for orders above the threshold, and shipping never waits for it.
- *Create shipment* calls the fulfillment API. Its Settings tab shows a retry policy: up to
  four attempts, exponential backoff from one second with jitter. The demo fulfillment API
  answers `503` to every first attempt for an order, so every successful run shows one
  retry.
- *Archive to S3* writes the order and the shipment to the workflow data bucket (SSE-KMS on
  Floci); *Publish order event* sends a message to the `order-events` queue.

The editor saves the draft as you type. *Publish* makes the draft an immutable version;
active workflows switch to it at once, while running executions finish on the version they
started with.

## 2. An order arrives

The [quickstart](quickstart-local.md#five-minutes-with-the-demo) shows the `curl` command
that signs and sends an order. The API:

1. finds the active trigger for the path, checks the signature and the body size;
2. creates the execution and its first step in one transaction, keyed by the idempotency key;
3. answers `202` with the `execution_id`, then signals the workers through Valkey.

Send the same request again: the answer is `200` with `"duplicate": true` and the same
execution id. Nothing ships twice.

## 3. Watching it run

**Executions, then the new run.** The page polls while the run is active:

- the **graph** colours each node by outcome and draws the path that ran; the branch that
  did not run is dashed;
- the **timeline** places every step on one time axis, so the retry wait before the second
  attempt of *Create shipment* is visible;
- the **step panel** (click a node or a timeline row) shows the attempt count, the input,
  the output and the log lines of that step, including the `503` and the retry it scheduled.

Under the hood a worker claimed each step with `FOR UPDATE SKIP LOCKED`, ran it, and
committed its result together with the steps it unlocked. The retry was a row update:
`status = queued`, `available_at = now + backoff`.

## 4. A failure

**Executions, filtered by *Failed*.** Three of the seeded orders arrived without an order
id; the fulfillment API refused them with `422`. A `422` is not retryable, so the step
failed at once, the execution failed, and:

- a **dead letter** holds the failed step with its input (**Dead letters**);
- the engine published `execution.failed`, which started *Tell on-call when a workflow
  fails*: open http://localhost:9131/slack to see the message in `#on-call`, and
  http://localhost:9130 for the emails the workflows sent.

## 5. Resume from the failed step

Fix the cause (here: the order needs an id, so the sender must resend), or, for a transient
cause, simply **Retry** the dead letter. The execution resumes from the failed step with the
same input, keeping everything that already succeeded. **Run again** on an execution starts a
new execution from the beginning with the same payload instead.

## 6. The rest of the operations view

- **Event bus**: publish `lead.created` with a company domain; *Enrich and route new leads*
  starts, calls the CRM, branches by segment and merges back.
- **Credentials**: secrets are write-only. Editing shows the public fields only; leaving a
  secret blank keeps the stored value.
- **Settings**: workspace time zone and retention, variables (`{{ env.KEY }}` in templates),
  members and roles, API keys (`wfk_...`, shown once) and the append-only audit log.
- **Dashboard**: success rate, daily volume in the workspace's time zone, the slowest
  workflows, recent failures, the queue and the workers.

## 7. Where the tests are

| Behaviour | Test |
| --- | --- |
| Signed webhooks, idempotency, retries, archive | `e2e/tests/executions.spec.ts`, `apps/api/tests/integration/test_triggers.py` |
| Retries, backoff, dead letters, resume | `apps/api/tests/integration/test_engine_reliability.py` |
| Branches, merges, loops | `apps/api/tests/unit/test_routing.py`, `apps/api/tests/integration/test_engine_runs.py` |
| Building and publishing in the editor | `e2e/tests/editor.spec.ts` |
| Events, credentials, settings | `e2e/tests/operate.spec.ts` |
