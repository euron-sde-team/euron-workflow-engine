import { describe, expect, it } from "vitest";

import { isActive, iterationLabel, nodeRuns, ranNodes, timeline } from "@/lib/executions";
import type { StepSummary } from "@/lib/types";

function step(overrides: Partial<StepSummary>): StepSummary {
  return {
    id: overrides.id ?? Math.random().toString(36).slice(2),
    node_id: "fetch",
    node_type: "integration.http_request",
    node_name: "Fetch",
    run_index: 0,
    scope: "",
    status: "succeeded",
    attempt: 1,
    max_attempts: 3,
    ports: ["main"],
    error: null,
    available_at: null,
    started_at: null,
    finished_at: null,
    duration_ms: null,
    ...overrides,
  };
}

describe("isActive", () => {
  it("treats queued, running and waiting as in progress", () => {
    expect(["queued", "running", "waiting"].every((s) => isActive(s as "queued"))).toBe(true);
    expect(isActive("succeeded")).toBe(false);
    expect(isActive("skipped")).toBe(false);
  });
});

describe("iterationLabel", () => {
  it("counts loop passes from one", () => {
    expect(iterationLabel("")).toBeNull();
    expect(iterationLabel("/batches:0")).toBe("pass 1");
    expect(iterationLabel("/outer:1/inner:3")).toBe("pass 2.4");
  });

  it("ignores scopes it cannot read", () => {
    expect(iterationLabel("/odd:x")).toBeNull();
  });
});

describe("nodeRuns", () => {
  it("prefers active steps, then failures, then the latest success", () => {
    const runs = nodeRuns([
      step({ id: "a", node_id: "loop-body", status: "succeeded", scope: "/l:0" }),
      step({ id: "b", node_id: "loop-body", status: "failed", scope: "/l:1" }),
      step({ id: "c", node_id: "loop-body", status: "succeeded", scope: "/l:2" }),
      step({ id: "d", node_id: "notify", status: "running" }),
      step({ id: "e", node_id: "notify", status: "succeeded" }),
      step({ id: "f", node_id: "fallback", status: "skipped" }),
      step({ id: "g", node_id: "done", status: "succeeded" }),
      step({ id: "h", node_id: "done", status: "succeeded" }),
    ]);
    expect(runs.get("loop-body")).toMatchObject({ status: "failed", runs: 3, focus: { id: "b" } });
    expect(runs.get("notify")).toMatchObject({ status: "running", focus: { id: "d" } });
    expect(runs.get("fallback")).toMatchObject({ status: "skipped", runs: 0 });
    expect(runs.get("done")?.focus.id).toBe("h");
  });
});

describe("timeline", () => {
  const base = Date.parse("2026-10-01T10:00:00Z");
  const at = (ms: number) => new Date(base + ms).toISOString();

  it("places steps on one axis from the execution start", () => {
    const result = timeline({
      created_at: at(0),
      started_at: at(0),
      finished_at: at(1000),
      steps: [
        step({
          id: "2",
          node_id: "second",
          node_name: "Second",
          started_at: at(500),
          finished_at: at(1000),
        }),
        step({
          id: "1",
          node_id: "first",
          node_name: "First",
          started_at: at(0),
          finished_at: at(500),
        }),
        step({ id: "s", status: "skipped" }),
      ],
    });
    expect(result.spanMs).toBe(1000);
    expect(result.skipped).toBe(1);
    expect(result.rows.map((r) => [r.label, r.offset, r.width])).toEqual([
      ["First", 0, 0.5],
      ["Second", 0.5, 0.5],
    ]);
  });

  it("runs open steps up to now and labels repeats", () => {
    const result = timeline(
      {
        created_at: at(0),
        started_at: at(0),
        finished_at: null,
        steps: [
          step({ node_name: "Poll", run_index: 0, started_at: at(0), finished_at: at(100) }),
          step({ node_name: "Poll", run_index: 1, started_at: at(100), status: "running" }),
          step({
            node_name: "Batch",
            node_id: "b",
            scope: "/loop:1",
            started_at: at(150),
            finished_at: at(160),
          }),
        ],
      },
      base + 200,
    );
    expect(result.rows.map((r) => r.label)).toEqual([
      "Poll, run 1",
      "Poll, run 2",
      "Batch, pass 2",
    ]);
    expect(result.rows[1]!.width).toBeCloseTo(0.5);
  });

  it("keeps tiny steps visible", () => {
    const result = timeline({
      created_at: at(0),
      started_at: at(0),
      finished_at: at(100_000),
      steps: [step({ started_at: at(10), finished_at: at(10) })],
    });
    expect(result.rows[0]!.width).toBeGreaterThan(0);
  });
});

describe("ranNodes", () => {
  it("leaves out skipped and not yet started nodes", () => {
    const ran = ranNodes([
      step({ node_id: "a" }),
      step({ node_id: "b", status: "skipped" }),
      step({ node_id: "c", status: "queued" }),
    ]);
    expect([...ran]).toEqual(["a"]);
  });
});
