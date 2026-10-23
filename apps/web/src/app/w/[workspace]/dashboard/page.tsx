"use client";

import {
  Activity,
  Archive,
  CalendarClock,
  Crown,
  Gauge,
  Server,
  Timer,
  TriangleAlert,
  Workflow as WorkflowIcon,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState, type ReactNode } from "react";

import { VolumeChart } from "@/components/dashboard/volume-chart";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorNotice, Skeleton } from "@/components/ui/feedback";
import { PageBody, PageHeader } from "@/components/ui/page";
import { cn } from "@/lib/cn";
import { formatDuration, formatNumber, formatPercent, formatRelative } from "@/lib/format";
import { useDashboard } from "@/lib/queries";
import type { DashboardWindow } from "@/lib/types";

const WINDOWS: { value: DashboardWindow; label: string }[] = [
  { value: "24h", label: "24 hours" },
  { value: "7d", label: "7 days" },
  { value: "14d", label: "14 days" },
  { value: "30d", label: "30 days" },
];

function Kpi({
  icon,
  label,
  value,
  detail,
  href,
  tone,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  detail: ReactNode;
  href?: string;
  tone?: "danger";
}) {
  const body = (
    <Card className={cn("h-full px-5 py-4", href && "hover:border-input transition-colors")}>
      <div className="text-muted-foreground [&_svg]:text-primary flex items-center gap-2 text-[12.5px] font-medium [&_svg]:size-4">
        {icon}
        {label}
      </div>
      <p
        className={cn(
          "mt-2 text-[26px] font-semibold tracking-tight tabular-nums",
          tone === "danger" && "text-danger",
        )}
      >
        {value}
      </p>
      <p className="text-muted-foreground mt-0.5 text-xs">{detail}</p>
    </Card>
  );
  return href ? (
    <Link href={href} className="block rounded-xl">
      {body}
    </Link>
  ) : (
    body
  );
}

export default function DashboardPage() {
  const { workspace } = useParams<{ workspace: string }>();
  const [window, setWindow] = useState<DashboardWindow>("7d");
  const dashboard = useDashboard(workspace, window);
  const data = dashboard.data;
  const base = `/w/${workspace}`;

  return (
    <PageBody>
      <PageHeader
        title="Dashboard"
        description="How your automations are doing, and what is happening right now."
        actions={
          <div
            role="tablist"
            aria-label="Time window"
            className="border-border bg-card flex rounded-lg border p-0.5 shadow-sm"
          >
            {WINDOWS.map((option) => (
              <button
                key={option.value}
                type="button"
                role="tab"
                aria-selected={window === option.value}
                onClick={() => setWindow(option.value)}
                className={cn(
                  "rounded-md px-2.5 py-1 text-[12.5px] font-medium transition-colors",
                  window === option.value
                    ? "bg-accent text-accent-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {option.label}
              </button>
            ))}
          </div>
        }
      />
      {dashboard.error ? <ErrorNotice message={dashboard.error.message} /> : null}
      {!data ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-28" />
          ))}
          <Skeleton className="h-72 sm:col-span-2 lg:col-span-4" />
        </div>
      ) : (
        <div className="space-y-5">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Kpi
              icon={<Gauge />}
              label="Success rate"
              value={data.success_rate === null ? "-" : formatPercent(data.success_rate, 1)}
              detail={`${formatNumber(data.totals.succeeded)} succeeded, ${formatNumber(data.totals.failed)} failed`}
            />
            <Kpi
              icon={<Activity />}
              label="Executions"
              value={formatNumber(data.totals.total)}
              detail={`${formatNumber(data.totals.in_progress)} in progress, ${formatNumber(data.totals.cancelled)} cancelled`}
              href={`${base}/executions`}
            />
            <Kpi
              icon={<Timer />}
              label="Duration, p95"
              value={formatDuration(data.p95_ms)}
              detail={`Median ${formatDuration(data.p50_ms)}`}
            />
            <Kpi
              icon={<Archive />}
              label="Open dead letters"
              value={formatNumber(data.dead_letters_open)}
              detail={`${data.active_workflows} of ${data.workflows} workflows active`}
              href={`${base}/dead-letters`}
              tone={data.dead_letters_open > 0 ? "danger" : undefined}
            />
          </div>

          <Card>
            <CardHeader>
              <div>
                <CardTitle>Volume</CardTitle>
                <CardDescription>
                  Executions started per {window === "24h" ? "hour" : "day"} ({data.timezone})
                </CardDescription>
              </div>
              <div className="text-muted-foreground hidden flex-wrap gap-3 text-[12px] sm:flex">
                {[
                  ["Succeeded", "var(--chart-success)"],
                  ["Failed", "var(--chart-failed)"],
                  ["Cancelled", "var(--chart-cancelled)"],
                  ["In progress", "var(--chart-progress)"],
                ].map(([name, color]) => (
                  <span key={name} className="flex items-center gap-1.5">
                    <span className="size-2 rounded-full" style={{ background: color }} />
                    {name}
                  </span>
                ))}
              </div>
            </CardHeader>
            <CardContent>
              <VolumeChart volume={data.volume} />
            </CardContent>
          </Card>

          <div className="grid gap-5 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <div>
                  <CardTitle>Slowest workflows</CardTitle>
                  <CardDescription>By 95th percentile duration of successful runs</CardDescription>
                </div>
              </CardHeader>
              <CardContent className="pt-2">
                {data.slowest.length === 0 ? (
                  <p className="text-muted-foreground py-6 text-center text-[13px]">
                    Not enough runs yet.
                  </p>
                ) : (
                  <table className="w-full text-[13px]">
                    <thead>
                      <tr className="text-subtle text-left text-[11.5px] tracking-wide uppercase">
                        <th className="pb-2 font-medium">Workflow</th>
                        <th className="pb-2 text-right font-medium">Runs</th>
                        <th className="pb-2 text-right font-medium">p95</th>
                        <th className="pb-2 text-right font-medium">Average</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.slowest.map((row) => (
                        <tr key={row.workflow_id} className="border-border border-t">
                          <td className="py-2 pr-2">
                            <Link
                              href={`${base}/workflows/${row.workflow_id}`}
                              className="hover:text-primary font-medium"
                            >
                              {row.name}
                            </Link>
                          </td>
                          <td className="text-muted-foreground py-2 text-right tabular-nums">
                            {formatNumber(row.runs)}
                          </td>
                          <td className="py-2 text-right font-medium tabular-nums">
                            {formatDuration(row.p95_ms)}
                          </td>
                          <td className="text-muted-foreground py-2 text-right tabular-nums">
                            {formatDuration(row.avg_ms)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <div>
                  <CardTitle>Recent failures</CardTitle>
                  <CardDescription>The latest executions that failed</CardDescription>
                </div>
              </CardHeader>
              <CardContent className="pt-2">
                {data.recent_failures.length === 0 ? (
                  <EmptyState
                    icon={<Gauge />}
                    title="No failures"
                    description="Everything that ran in this window succeeded."
                    className="py-6"
                  />
                ) : (
                  <ul className="divide-border divide-y">
                    {data.recent_failures.map((failure) => (
                      <li key={failure.execution_id}>
                        <Link
                          href={`${base}/executions/${failure.execution_id}`}
                          className="hover:text-primary flex items-start gap-3 py-2.5"
                        >
                          <TriangleAlert
                            className="text-danger mt-0.5 size-4 shrink-0"
                            aria-hidden
                          />
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-[13px] font-medium">
                              {failure.workflow_name}
                            </span>
                            <span className="text-muted-foreground block truncate text-[12px]">
                              {failure.code ? (
                                <span className="font-mono">{failure.code}</span>
                              ) : null}{" "}
                              {failure.message}
                            </span>
                          </span>
                          <span className="text-subtle shrink-0 text-[12px]">
                            {failure.finished_at ? formatRelative(failure.finished_at) : ""}
                          </span>
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>
          </div>

          <div className="grid gap-5 lg:grid-cols-3">
            <Card>
              <CardHeader>
                <div>
                  <CardTitle>Queue</CardTitle>
                  <CardDescription>Steps waiting for a worker right now</CardDescription>
                </div>
              </CardHeader>
              <CardContent className="grid grid-cols-2 gap-3 pt-3">
                {[
                  ["Ready", data.queue.steps_ready],
                  ["Running", data.queue.steps_running],
                  ["Waiting", data.queue.steps_waiting],
                  ["Queued runs", data.queue.executions_queued],
                ].map(([label, value]) => (
                  <div
                    key={label}
                    className="border-border bg-muted/50 rounded-lg border px-3 py-2"
                  >
                    <p className="text-muted-foreground text-[11.5px]">{label}</p>
                    <p className="text-lg font-semibold tabular-nums">
                      {formatNumber(Number(value))}
                    </p>
                  </div>
                ))}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <div>
                  <CardTitle>Workers</CardTitle>
                  <CardDescription>
                    Processes claiming steps; one leads the scheduler
                  </CardDescription>
                </div>
              </CardHeader>
              <CardContent className="pt-2">
                {data.workers.length === 0 ? (
                  <p className="text-muted-foreground py-4 text-center text-[13px]">
                    No worker has reported in.
                  </p>
                ) : (
                  <ul className="space-y-2">
                    {data.workers.map((worker) => (
                      <li key={worker.id} className="flex items-center gap-2.5 text-[13px]">
                        <Server className="text-muted-foreground size-4" aria-hidden />
                        <span className="min-w-0 flex-1 truncate font-mono text-[12px]">
                          {worker.id}
                        </span>
                        {worker.leader ? (
                          <Badge tone="primary">
                            <Crown aria-hidden /> Leader
                          </Badge>
                        ) : null}
                        <span className="text-muted-foreground tabular-nums">
                          {worker.busy}/{worker.concurrency}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <div>
                  <CardTitle>Next runs</CardTitle>
                  <CardDescription>Upcoming schedules and intervals</CardDescription>
                </div>
              </CardHeader>
              <CardContent className="pt-2">
                {data.upcoming.length === 0 ? (
                  <p className="text-muted-foreground py-4 text-center text-[13px]">
                    Nothing scheduled.
                  </p>
                ) : (
                  <ul className="space-y-2">
                    {data.upcoming.map((run) => (
                      <li
                        key={`${run.workflow_id}-${run.node_id}`}
                        className="flex items-center gap-2.5 text-[13px]"
                      >
                        {run.kind === "cron" ? (
                          <CalendarClock className="text-muted-foreground size-4" aria-hidden />
                        ) : (
                          <WorkflowIcon className="text-muted-foreground size-4" aria-hidden />
                        )}
                        <Link
                          href={`${base}/workflows/${run.workflow_id}`}
                          className="hover:text-primary min-w-0 flex-1 truncate"
                        >
                          {run.workflow_name}
                        </Link>
                        <span className="text-subtle shrink-0 text-[12px]">
                          {formatRelative(run.next_fire_at)}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </PageBody>
  );
}
