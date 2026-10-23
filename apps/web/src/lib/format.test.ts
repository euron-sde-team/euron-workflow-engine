import { describe, expect, it } from "vitest";

import {
  formatDuration,
  formatPercent,
  formatRelative,
  initials,
  prettyJson,
  shortId,
} from "@/lib/format";

describe("formatDuration", () => {
  it.each([
    [null, "-"],
    [840, "840 ms"],
    [2400, "2.4 s"],
    [38_000, "38 s"],
    [245_000, "4 min 05 s"],
    [7_800_000, "2 h 10 min"],
  ])("formats %s", (ms, expected) => {
    expect(formatDuration(ms)).toBe(expected);
  });
});

describe("formatRelative", () => {
  const now = new Date("2026-10-23T12:00:00Z");
  it("speaks in the largest unit", () => {
    expect(formatRelative("2026-10-23T11:58:00Z", now)).toBe("2 minutes ago");
    expect(formatRelative("2026-10-21T12:00:00Z", now)).toBe("2 days ago");
    expect(formatRelative("2026-10-23T13:00:00Z", now)).toBe("in 1 hour");
    expect(formatRelative("2026-10-23T12:00:10Z", now)).toBe("in a moment");
  });
});

describe("small helpers", () => {
  it("formats percents, initials, ids and json", () => {
    expect(formatPercent(0.9567, 1)).toBe("95.7%");
    expect(initials("Maya Patel")).toBe("MP");
    expect(initials("  ")).toBe("?");
    expect(shortId("01a168de-5609-76ae-a5c9-343b8d8f93a2")).toBe("8d8f93a2");
    expect(prettyJson({ a: 1 })).toBe('{\n  "a": 1\n}');
    expect(prettyJson("x".repeat(30), 10)).toContain("more characters");
  });
});
