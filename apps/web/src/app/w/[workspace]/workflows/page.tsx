"use client";

import { CalendarClock, Hand, RadioTower, Search, Timer, Webhook, Workflow as WorkflowIcon } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useDeferredValue, useState } from "react";

import { StatusDot } from "@/components/status";
import { ImportButton, NewWorkflowButton } from "@/components/workflows/new-workflow-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorNotice, Skeleton } from "@/components/ui/feedback";
import { Input, NativeSelect } from "@/components/ui/input";
import { PageBody, PageHeader } from "@/components/ui/page";
import { Tooltip } from "@/components/ui/tooltip";
import { formatPercent, formatRelative } from "@/lib/format";
import { canEdit, useCurrentWorkspace, useWorkflows } from "@/lib/queries";
import type { WorkflowSummary } from "@/lib/types";

const TRIGGER_ICONS: Record<string, typeof Hand> = {
  manual: Hand,
  webhook: Webhook,
  cron: CalendarClock,
  interval: Timer,
  event: RadioTower,
};

function StateBadge({ workflow }: { workflow: WorkflowSummary }) {
  if (workflow.active) return <Badge tone="success">Active</Badge>;
  if (workflow.published_version === null) return <Badge tone="outline">Draft</Badge>;
  return <Badge tone="neutral">Inactive</Badge>;
}

function SuccessRate({ workflow }: { workflow: WorkflowSummary }) {
  const { stats_7d: stats } = workflow;
  if (!stats.total) return <span className="text-subtle">-</span>;
  const rate = stats.success_rate;
  return (
    <Tooltip content={`${stats.succeeded} succeeded, ${stats.failed} failed of ${stats.total} in 7 days`}>
      <span className="inline-flex items-center gap-2">
        <span className="h-1.5 w-14 overflow-hidden rounded-full bg-muted">
          <span className="block h-full rounded-full bg-success" style={{ width: `${(rate ?? 0) * 100}%` }} />
        </span>
        <span className="tabular-nums">{rate === null ? "-" : formatPercent(rate)}</span>
      </span>
    </Tooltip>
  );
}

export default function WorkflowsPage() {
  const { workspace } = useParams<{ workspace: string }>();
  const current = useCurrentWorkspace(workspace);
  const [search, setSearch] = useState("");
  const [active, setActive] = useState("");
  const deferred = useDeferredValue(search);
  const workflows = useWorkflows(workspace, { search: deferred, active });
  const editable = canEdit(current?.role);
  const items = workflows.data?.items;

  return (
    <PageBody>
      <PageHeader
        title="Workflows"
        description="Every automation in this workspace. Active workflows listen to their triggers."
        actions={
          editable ? (
            <>
              <ImportButton workspace={workspace} />
              <NewWorkflowButton workspace={workspace} />
            </>
          ) : null
        }
      />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative min-w-56 flex-1 sm:max-w-sm">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-subtle" aria-hidden />
          <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search workflows" className="pl-9" aria-label="Search workflows" />
        </div>
        <NativeSelect value={active} onChange={(e) => setActive(e.target.value)} className="w-40" aria-label="Filter by state">
          <option value="">All workflows</option>
          <option value="true">Active</option>
          <option value="false">Not active</option>
        </NativeSelect>
        {workflows.data ? <span className="ml-auto text-[12.5px] text-muted-foreground">{workflows.data.total} workflows</span> : null}
      </div>
      {workflows.error ? <ErrorNotice message={workflows.error.message} /> : null}
      {!items ? (
        <Skeleton className="h-80" />
      ) : items.length === 0 ? (
        <Card>
          <EmptyState
            icon={<WorkflowIcon />}
            title={search || active ? "No workflow matches" : "No workflows yet"}
            description="Start from a template, import an exported workflow, or build one on the canvas."
            action={
              <Button asChild variant="secondary">
                <Link href={`/w/${workspace}/templates`}>Browse templates</Link>
              </Button>
            }
          />
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[46rem] text-[13px]">
              <thead className="border-b border-border bg-muted/50 text-left text-[11.5px] uppercase tracking-wide text-subtle">
                <tr>
                  <th className="px-4 py-2.5 font-medium">Workflow</th>
                  <th className="px-3 py-2.5 font-medium">Triggers</th>
                  <th className="px-3 py-2.5 font-medium">State</th>
                  <th className="px-3 py-2.5 font-medium">Last run</th>
                  <th className="px-3 py-2.5 font-medium">7-day success</th>
                  <th className="px-4 py-2.5 font-medium">Next run</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {items.map((workflow) => (
                  <tr key={workflow.id} className="transition-colors hover:bg-muted/40">
                    <td className="max-w-[22rem] px-4 py-3">
                      <Link href={`/w/${workspace}/workflows/${workflow.id}`} className="block font-medium hover:text-primary" data-testid="workflow-link">
                        {workflow.name}
                      </Link>
                      <span className="mt-0.5 block truncate text-[12px] text-muted-foreground">{workflow.description || "No description"}</span>
                      {workflow.tags.length ? (
                        <span className="mt-1 flex flex-wrap gap-1">
                          {workflow.tags.map((tag) => (
                            <Badge key={tag} tone="outline">
                              {tag}
                            </Badge>
                          ))}
                        </span>
                      ) : null}
                    </td>
                    <td className="px-3 py-3">
                      <span className="flex gap-1.5 text-muted-foreground">
                        {workflow.trigger_kinds.map((kind) => {
                          const Icon = TRIGGER_ICONS[kind] ?? Hand;
                          return (
                            <Tooltip key={kind} content={kind}>
                              <Icon className="size-4" aria-label={kind} />
                            </Tooltip>
                          );
                        })}
                      </span>
                    </td>
                    <td className="px-3 py-3">
                      <span className="flex flex-col items-start gap-1">
                        <StateBadge workflow={workflow} />
                        {workflow.published_version ? (
                          <span className="text-[11.5px] text-muted-foreground">
                            v{workflow.published_version}
                            {workflow.has_unpublished_changes ? ", draft changed" : ""}
                          </span>
                        ) : null}
                      </span>
                    </td>
                    <td className="px-3 py-3">
                      {workflow.last_execution ? (
                        <Link href={`/w/${workspace}/executions/${workflow.last_execution.id}`} className="flex items-center gap-2 text-muted-foreground hover:text-foreground">
                          <StatusDot status={workflow.last_execution.status} />
                          {formatRelative(workflow.last_execution.created_at)}
                        </Link>
                      ) : (
                        <span className="text-subtle">Never</span>
                      )}
                    </td>
                    <td className="px-3 py-3">
                      <SuccessRate workflow={workflow} />
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">{workflow.next_run_at ? formatRelative(workflow.next_run_at) : <span className="text-subtle">-</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </PageBody>
  );
}
