import { describe, expect, it } from "vitest";

import type { WorkspaceSummary } from "@/lib/types";
import { pickWorkspace } from "@/lib/workspace-choice";

const workspace = (slug: string, workflow_count: number): WorkspaceSummary => ({
  id: slug,
  slug,
  name: slug,
  role: "owner",
  workflow_count,
  active_workflow_count: 0,
  member_count: 1,
});

describe("pickWorkspace", () => {
  const list = [workspace("atlas", 3), workspace("northwind", 9), workspace("zeta", 9)];

  it("returns to the workspace used last", () => {
    expect(pickWorkspace(list, "atlas")).toBe("atlas");
  });

  it("otherwise opens the fullest workspace, the first one on a tie", () => {
    expect(pickWorkspace(list, null)).toBe("northwind");
    expect(pickWorkspace(list, "removed")).toBe("northwind");
  });

  it("has nothing to open without workspaces", () => {
    expect(pickWorkspace([], "atlas")).toBeNull();
  });
});
