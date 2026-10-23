"use client";

import { Hourglass, X } from "lucide-react";
import type { ReactNode } from "react";

import { JsonView } from "@/components/json-view";
import { LogList } from "@/components/executions/log-list";
import { NodeIcon } from "@/components/node-icon";
import { StatusBadge } from "@/components/status";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/feedback";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { isActive, iterationLabel } from "@/lib/executions";
import { formatDateTime, formatDuration } from "@/lib/format";
import { useStep } from "@/lib/queries";
import type { LogLine, NodeType, StepSummary } from "@/lib/types";

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-subtle text-[11px] tracking-wide uppercase">{label}</dt>
      <dd className="truncate text-[12.5px]">{children}</dd>
    </div>
  );
}

/** Input, output, error and logs of one step. */
export function StepPanel({
  workspace,
  executionId,
  summary,
  nodeType,
  logs,
  onClose,
}: {
  workspace: string;
  executionId: string;
  summary: StepSummary;
  nodeType: NodeType | undefined;
  logs: LogLine[];
  onClose: () => void;
}) {
  const live = isActive(summary.status);
  const step = useStep(workspace, executionId, summary.id, live);
  const pass = iterationLabel(summary.scope);
  const mine = logs.filter((line) => line.step_id === summary.id);
  return (
    <div className="flex h-full flex-col" data-testid="step-panel">
      <div className="border-border flex items-start gap-3 border-b px-4 py-3.5">
        <NodeIcon icon={nodeType?.icon ?? "blocks"} category={nodeType?.category} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-[14px] font-semibold">{summary.node_name}</p>
          <p className="text-muted-foreground truncate text-[12px]">
            {nodeType?.name ?? summary.node_type}
            {pass ? `, ${pass}` : ""}
          </p>
        </div>
        <Button variant="ghost" size="icon-sm" aria-label="Close step" onClick={onClose}>
          <X />
        </Button>
      </div>
      <div className="space-y-4 px-4 py-4">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={summary.status} />
          {summary.ports.length &&
          summary.status === "succeeded" &&
          !(summary.ports.length === 1 && summary.ports[0] === "main") ? (
            <Badge tone="outline">took {summary.ports.join(", ")}</Badge>
          ) : null}
        </div>
        <dl className="grid grid-cols-2 gap-3">
          <Fact label="Attempt">
            {summary.attempt} of {summary.max_attempts}
          </Fact>
          <Fact label="Duration">{formatDuration(summary.duration_ms)}</Fact>
          <Fact label="Started">
            {summary.started_at ? formatDateTime(summary.started_at) : "-"}
          </Fact>
          <Fact label="Finished">
            {summary.finished_at ? formatDateTime(summary.finished_at) : "-"}
          </Fact>
        </dl>
        {summary.status === "waiting" && summary.available_at ? (
          <p className="bg-warning-soft text-warning flex items-center gap-2 rounded-lg px-3 py-2 text-[12.5px]">
            <Hourglass className="size-4" aria-hidden />
            Resumes {formatDateTime(summary.available_at)}
          </p>
        ) : null}
        {summary.error ? (
          <div
            className="border-danger/30 bg-danger-soft rounded-lg border px-3 py-2.5 text-[12.5px]"
            role="alert"
          >
            <p className="text-danger font-mono text-[11.5px] font-semibold">
              {summary.error.code}
            </p>
            <p className="text-foreground mt-0.5">{summary.error.message}</p>
            {summary.error.retryable !== undefined ? (
              <p className="text-muted-foreground mt-1 text-[11.5px]">
                {summary.error.retryable ? "Retryable error" : "Not retryable"}
              </p>
            ) : null}
          </div>
        ) : null}
      </div>
      <Tabs
        defaultValue={summary.status === "failed" ? "input" : "output"}
        className="flex min-h-0 flex-1 flex-col px-4 pb-4"
      >
        <TabsList>
          <TabsTrigger value="input">Input</TabsTrigger>
          <TabsTrigger value="output">Output</TabsTrigger>
          <TabsTrigger value="logs">Logs {mine.length ? `(${mine.length})` : ""}</TabsTrigger>
          {summary.error?.details !== undefined ? (
            <TabsTrigger value="error">Error details</TabsTrigger>
          ) : null}
        </TabsList>
        <TabsContent value="input">
          {step.data ? (
            <JsonView value={step.data.input} label="Step input" empty="No input." />
          ) : (
            <Skeleton className="h-32" />
          )}
        </TabsContent>
        <TabsContent value="output">
          {step.data ? (
            <JsonView
              value={step.data.output}
              label="Step output"
              empty={live ? "Not finished yet." : "No output."}
            />
          ) : (
            <Skeleton className="h-32" />
          )}
        </TabsContent>
        <TabsContent value="logs">
          <LogList lines={mine} empty="This step wrote no log lines." />
        </TabsContent>
        {summary.error?.details !== undefined ? (
          <TabsContent value="error">
            <JsonView value={summary.error.details} label="Error details" />
          </TabsContent>
        ) : null}
      </Tabs>
    </div>
  );
}
