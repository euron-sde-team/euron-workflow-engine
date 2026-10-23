import type { WorkspaceSummary } from "@/lib/types";

/**
 * Where to land after sign-in: the workspace used last on this device when the person still
 * belongs to it, otherwise the one with the most workflows (the list arrives sorted by name,
 * which would favour an almost empty workspace that happens to sort first).
 */
export function pickWorkspace(workspaces: WorkspaceSummary[], last: string | null): string | null {
  if (last && workspaces.some((w) => w.slug === last)) return last;
  let best: WorkspaceSummary | null = null;
  for (const workspace of workspaces) {
    if (!best || workspace.workflow_count > best.workflow_count) best = workspace;
  }
  return best?.slug ?? null;
}
