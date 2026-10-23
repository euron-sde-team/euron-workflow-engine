import type { Execution, ExecutionStatus, StepStatus, StepSummary } from "@/lib/types";

const ACTIVE: ReadonlySet<string> = new Set(["queued", "running", "waiting"]);

export function isActive(status: ExecutionStatus | StepStatus): boolean {
  return ACTIVE.has(status);
}

/**
 * Loop iterations live in scopes such as `/batches:2` or `/outer:1/inner:0`.
 * People count from one, so those read as "pass 3" and "pass 2.1".
 */
export function iterationLabel(scope: string): string | null {
  if (!scope) return null;
  const passes = scope
    .split("/")
    .filter(Boolean)
    .map((part) => Number(part.slice(part.lastIndexOf(":") + 1)) + 1);
  return passes.every(Number.isFinite) && passes.length ? `pass ${passes.join(".")}` : null;
}

/** The order in which one node's runs decide its colour on the graph. */
const PRIORITY: StepStatus[] = ["running", "waiting", "queued", "failed", "succeeded", "cancelled", "skipped"];

export type NodeRun = { status: StepStatus; runs: number; focus: StepSummary };

/**
 * One entry per node that has steps: how many times it ran (skips not counted) and the step
 * that best explains it, which is an active one, then a failure, then the latest run.
 */
export function nodeRuns(steps: StepSummary[]): Map<string, NodeRun> {
  const grouped = new Map<string, StepSummary[]>();
  for (const step of steps) grouped.set(step.node_id, [...(grouped.get(step.node_id) ?? []), step]);
  const result = new Map<string, NodeRun>();
  for (const [nodeId, list] of grouped) {
    const ran = list.filter((s) => s.status !== "skipped");
    const status = PRIORITY.find((p) => list.some((s) => s.status === p)) ?? "skipped";
    const focus = status === "succeeded" ? list.findLast((s) => s.status === "succeeded")! : list.find((s) => s.status === status)!;
    result.set(nodeId, { status, runs: ran.length, focus });
  }
  return result;
}

export type TimelineRow = {
  step: StepSummary;
  label: string;
  /** Fractions of the whole execution, both between 0 and 1. */
  offset: number;
  width: number;
};

export type Timeline = { rows: TimelineRow[]; spanMs: number; startedAt: number | null; skipped: number };

/** Lays the steps that started on one time axis, from the first start to the end (or now). */
export function timeline(
  execution: Pick<Execution, "created_at" | "started_at" | "finished_at" | "steps">,
  now: number = Date.now(),
): Timeline {
  const started = execution.steps.filter((s) => s.started_at);
  const skipped = execution.steps.filter((s) => s.status === "skipped").length;
  const firstStart = started.length ? Math.min(...started.map((s) => Date.parse(s.started_at!))) : null;
  const t0 = Math.min(
    ...[execution.started_at, execution.created_at].filter((v): v is string => Boolean(v)).map(Date.parse),
    firstStart ?? Number.POSITIVE_INFINITY,
  );
  const end = (step: StepSummary) => (step.finished_at ? Date.parse(step.finished_at) : now);
  const t1 = Math.max(
    execution.finished_at ? Date.parse(execution.finished_at) : now,
    ...started.map(end),
    t0 + 1,
  );
  const span = t1 - t0;
  const counts = new Map<string, number>();
  for (const step of started) counts.set(step.node_id, (counts.get(step.node_id) ?? 0) + 1);
  const rows = started
    .map((step) => {
      const begin = Date.parse(step.started_at!);
      const pass = iterationLabel(step.scope);
      const repeat = !pass && (counts.get(step.node_id) ?? 0) > 1 ? `run ${step.run_index + 1}` : null;
      return {
        step,
        label: [step.node_name, pass ?? repeat].filter(Boolean).join(", "),
        offset: Math.min(Math.max((begin - t0) / span, 0), 1),
        width: Math.min(Math.max((end(step) - begin) / span, 0.004), 1),
      };
    })
    .sort((a, b) => a.offset - b.offset);
  return { rows, spanMs: span, startedAt: Number.isFinite(t0) ? t0 : null, skipped };
}

/** Which edges carried data: both ends have a step that did not skip. */
export function ranNodes(steps: StepSummary[]): Set<string> {
  return new Set(steps.filter((s) => s.status !== "skipped" && s.status !== "queued").map((s) => s.node_id));
}
