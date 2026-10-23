"use client";

import { ChevronLeft, ChevronRight, History, X } from "lucide-react";
import Link from "next/link";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { StatusBadge } from "@/components/status";
import { TriggerLabel } from "@/components/trigger-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorNotice, Skeleton } from "@/components/ui/feedback";
import { NativeSelect } from "@/components/ui/input";
import { PageBody, PageHeader } from "@/components/ui/page";
import { formatDateTime, formatDuration, formatRelative, shortId } from "@/lib/format";
import { useExecutions, useWorkflows, type ExecutionFilters } from "@/lib/queries";

const STATUSES = ["queued", "running", "waiting", "succeeded", "failed", "cancelled"];
const TRIGGERS = [
  ["manual", "Manual"],
  ["webhook", "Webhook"],
  ["cron", "Schedule"],
  ["interval", "Interval"],
  ["event", "Event"],
  ["retry", "Retry"],
];
const MODES = [
  ["production", "Production"],
  ["manual", "Manual"],
  ["test", "Test (draft)"],
];
const KEYS = ["status", "workflow_id", "trigger", "mode"] as const;

function ExecutionTable({ workspace, filters }: { workspace: string; filters: ExecutionFilters }) {
  // One cursor per page visited, so "Newer" can step back without a reverse cursor.
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const page = useExecutions(workspace, filters, cursors.at(-1) ?? null);
  const items = page.data?.items;
  const filtered = Object.values(filters).some(Boolean);

  if (page.error) return <ErrorNotice message={page.error.message} />;
  if (!items) return <Skeleton className="h-96" />;
  if (!items.length && cursors.length === 1) {
    return (
      <Card>
        <EmptyState
          icon={<History />}
          title={filtered ? "No execution matches these filters" : "No executions yet"}
          description="Runs appear here as soon as a trigger fires or someone runs a workflow."
        />
      </Card>
    );
  }
  return (
    <>
      <Card className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[48rem] text-[13px]">
            <thead className="border-b border-border bg-muted/50 text-left text-[11.5px] uppercase tracking-wide text-subtle">
              <tr>
                <th className="px-4 py-2.5 font-medium">Status</th>
                <th className="px-3 py-2.5 font-medium">Workflow</th>
                <th className="px-3 py-2.5 font-medium">Trigger</th>
                <th className="px-3 py-2.5 font-medium">Started</th>
                <th className="px-3 py-2.5 text-right font-medium">Duration</th>
                <th className="px-4 py-2.5 font-medium">Result</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {items.map((execution) => {
                const href = `/w/${workspace}/executions/${execution.id}`;
                return (
                  <tr key={execution.id} className="transition-colors hover:bg-muted/40">
                    <td className="px-4 py-2.5">
                      <Link href={href} className="block" data-testid="execution-link">
                        <StatusBadge status={execution.status} />
                      </Link>
                    </td>
                    <td className="max-w-[18rem] px-3 py-2.5">
                      <Link href={href} className="block truncate font-medium hover:text-primary">
                        {execution.workflow_name || "Deleted workflow"}
                      </Link>
                      <span className="font-mono text-[11px] text-subtle">{shortId(execution.id)}</span>
                    </td>
                    <td className="px-3 py-2.5">
                      <span className="flex items-center gap-2">
                        <TriggerLabel kind={execution.trigger_kind} />
                        {execution.mode === "test" ? <Badge tone="outline">test</Badge> : null}
                        {execution.resume_count ? <Badge tone="info">resumed</Badge> : null}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 text-muted-foreground" title={formatDateTime(execution.created_at)}>
                      {formatRelative(execution.created_at)}
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums text-muted-foreground">{formatDuration(execution.duration_ms)}</td>
                    <td className="max-w-[20rem] truncate px-4 py-2.5 text-[12.5px]">
                      {execution.error ? (
                        <span className="text-danger" title={execution.error.message}>
                          {execution.error.message}
                        </span>
                      ) : (
                        <span className="text-subtle">-</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>
      <div className="mt-3 flex items-center justify-end gap-2">
        <Button variant="secondary" size="sm" disabled={cursors.length === 1} onClick={() => setCursors((c) => c.slice(0, -1))}>
          <ChevronLeft /> Newer
        </Button>
        <Button
          variant="secondary"
          size="sm"
          disabled={!page.data?.next_cursor}
          onClick={() => {
            const next = page.data?.next_cursor;
            if (next) setCursors((c) => [...c, next]);
          }}
        >
          Older <ChevronRight />
        </Button>
      </div>
    </>
  );
}

function Executions() {
  const { workspace } = useParams<{ workspace: string }>();
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const workflows = useWorkflows(workspace, {}, 100);
  const filters: ExecutionFilters = Object.fromEntries(KEYS.map((key) => [key, params.get(key) ?? ""]));
  const any = KEYS.some((key) => filters[key]);

  function setFilter(key: (typeof KEYS)[number], value: string) {
    const next = new URLSearchParams(params.toString());
    if (value) next.set(key, value);
    else next.delete(key);
    const query = next.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }

  return (
    <PageBody>
      <PageHeader title="Executions" description="Every run, newest first. A failed run can resume from the step that failed." />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <NativeSelect value={filters.status} onChange={(e) => setFilter("status", e.target.value)} className="w-36" aria-label="Filter by status">
          <option value="">Any status</option>
          {STATUSES.map((status) => (
            <option key={status} value={status}>
              {status[0]!.toUpperCase() + status.slice(1)}
            </option>
          ))}
        </NativeSelect>
        <NativeSelect value={filters.workflow_id} onChange={(e) => setFilter("workflow_id", e.target.value)} className="w-56" aria-label="Filter by workflow">
          <option value="">All workflows</option>
          {workflows.data?.items.map((workflow) => (
            <option key={workflow.id} value={workflow.id}>
              {workflow.name}
            </option>
          ))}
        </NativeSelect>
        <NativeSelect value={filters.trigger} onChange={(e) => setFilter("trigger", e.target.value)} className="w-36" aria-label="Filter by trigger">
          <option value="">Any trigger</option>
          {TRIGGERS.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </NativeSelect>
        <NativeSelect value={filters.mode} onChange={(e) => setFilter("mode", e.target.value)} className="w-36" aria-label="Filter by mode">
          <option value="">Any mode</option>
          {MODES.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </NativeSelect>
        {any ? (
          <Button variant="ghost" size="sm" onClick={() => router.replace(pathname, { scroll: false })}>
            <X /> Clear
          </Button>
        ) : null}
      </div>
      <ExecutionTable key={KEYS.map((key) => filters[key]).join("|")} workspace={workspace} filters={filters} />
    </PageBody>
  );
}

export default function ExecutionsPage() {
  return (
    <Suspense
      fallback={
        <PageBody>
          <Skeleton className="h-96" />
        </PageBody>
      }
    >
      <Executions />
    </Suspense>
  );
}
