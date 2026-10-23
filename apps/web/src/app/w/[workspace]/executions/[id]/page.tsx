"use client";

import { Ban, ChevronRight, ExternalLink, MousePointerClick, Play, RotateCcw, StepForward } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { ExecutionGraph } from "@/components/executions/execution-graph";
import { LogList } from "@/components/executions/log-list";
import { StepPanel } from "@/components/executions/step-panel";
import { Timeline } from "@/components/executions/timeline";
import { JsonView } from "@/components/json-view";
import { StatusBadge } from "@/components/status";
import { TriggerLabel } from "@/components/trigger-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorNotice, Skeleton, Spinner } from "@/components/ui/feedback";
import { PageBody } from "@/components/ui/page";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { isActive, nodeRuns } from "@/lib/executions";
import { formatDateTime, formatDuration, shortId } from "@/lib/format";
import {
  canEdit,
  useCurrentWorkspace,
  useExecution,
  useExecutionActions,
  useExecutionDefinition,
  useLogs,
  useNodeTypes,
} from "@/lib/queries";
import type { Execution } from "@/lib/types";

function Actions({ workspace, execution, editable }: { workspace: string; execution: Execution; editable: boolean }) {
  const router = useRouter();
  const actions = useExecutionActions(workspace, execution.id);
  const busy = actions.cancel.isPending || actions.resume.isPending || actions.retry.isPending;
  const fail = (error: Error) => toast.error(error.message);
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button asChild variant="secondary">
        <Link href={`/w/${workspace}/workflows/${execution.workflow_id}`}>
          <ExternalLink /> Open workflow
        </Link>
      </Button>
      {editable && isActive(execution.status) ? (
        <Button
          variant="secondary"
          disabled={busy}
          data-testid="cancel-execution"
          onClick={() =>
            actions.cancel.mutate(undefined, { onSuccess: () => toast.success("Execution cancelled"), onError: fail })
          }
        >
          <Ban /> Cancel
        </Button>
      ) : null}
      {editable && execution.status === "failed" ? (
        <Button
          variant="secondary"
          disabled={busy}
          data-testid="resume-execution"
          onClick={() =>
            actions.resume.mutate(undefined, {
              onSuccess: () => toast.success("Resumed from the failed step"),
              onError: fail,
            })
          }
        >
          <StepForward /> Resume
        </Button>
      ) : null}
      {editable && !isActive(execution.status) ? (
        <Button
          disabled={busy}
          data-testid="retry-execution"
          onClick={() =>
            actions.retry.mutate(undefined, {
              onSuccess: (result) => {
                toast.success("Started a new run with the same payload");
                router.push(`/w/${workspace}/executions/${result.execution_id}`);
              },
              onError: fail,
            })
          }
        >
          {busy ? <Spinner className="text-primary-foreground" /> : <RotateCcw />} Run again
        </Button>
      ) : null}
    </div>
  );
}

export default function ExecutionPage() {
  const { workspace, id } = useParams<{ workspace: string; id: string }>();
  const current = useCurrentWorkspace(workspace);
  const query = useExecution(workspace, id);
  const execution = query.data;
  const live = execution ? isActive(execution.status) : false;
  const definition = useExecutionDefinition(workspace, id);
  const types = useNodeTypes();
  const logs = useLogs(workspace, id, live);
  // undefined: follow the failed step, if any; null: the panel was closed on purpose.
  const [selection, setSelection] = useState<string | null | undefined>(undefined);

  const steps = useMemo(() => execution?.steps ?? [], [execution?.steps]);
  const runs = useMemo(() => nodeRuns(steps), [steps]);
  const stepNames = useMemo(() => new Map(steps.map((s) => [s.id, s.node_name])), [steps]);
  const typeMap = useMemo(() => new Map((types.data ?? []).map((t) => [t.type, t])), [types.data]);

  if (query.error) {
    return (
      <PageBody>
        <ErrorNotice message={query.error.message} />
      </PageBody>
    );
  }
  if (!execution) {
    return (
      <PageBody className="max-w-7xl space-y-4">
        <Skeleton className="h-16" />
        <Skeleton className="h-96" />
      </PageBody>
    );
  }

  const failedStep = execution.error?.step_id ?? steps.find((s) => s.status === "failed")?.id ?? null;
  const selectedId = selection === undefined ? failedStep : selection;
  const selected = steps.find((s) => s.id === selectedId) ?? null;
  const failedNode = execution.error?.node_id ? steps.find((s) => s.node_id === execution.error?.node_id)?.node_name : null;

  return (
    <PageBody className="max-w-7xl">
      <nav className="mb-2 flex items-center gap-1 text-[12.5px] text-muted-foreground" aria-label="Breadcrumb">
        <Link href={`/w/${workspace}/executions`} className="hover:text-foreground">
          Executions
        </Link>
        <ChevronRight className="size-3.5" aria-hidden />
        <span className="font-mono">{shortId(execution.id)}</span>
      </nav>
      <header className="flex flex-wrap items-start justify-between gap-4 pb-5">
        <div className="min-w-0">
          <h1 className="flex flex-wrap items-center gap-3 text-[22px] font-semibold tracking-tight">
            {execution.workflow_name || "Deleted workflow"}
            <StatusBadge status={execution.status} className="text-[12px]" />
          </h1>
          <p className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-muted-foreground">
            <TriggerLabel kind={execution.trigger_kind} />
            <span>{execution.version_number ? `Version ${execution.version_number}` : "Draft test run"}</span>
            <span title={execution.created_at}>Started {formatDateTime(execution.started_at ?? execution.created_at)}</span>
            <span>{live ? "Running for" : "Took"} {formatDuration(execution.duration_ms ?? (query.dataUpdatedAt - Date.parse(execution.started_at ?? execution.created_at)))}</span>
            {execution.resume_count ? <Badge tone="info">resumed {execution.resume_count}x</Badge> : null}
            {execution.retry_of_id ? (
              <Link href={`/w/${workspace}/executions/${execution.retry_of_id}`} className="text-primary hover:underline">
                Retry of {shortId(execution.retry_of_id)}
              </Link>
            ) : null}
          </p>
        </div>
        <Actions workspace={workspace} execution={execution} editable={canEdit(current?.role)} />
      </header>

      {execution.error ? (
        <div className="mb-5 flex flex-wrap items-center gap-3 rounded-xl border border-danger/30 bg-danger-soft px-4 py-3" role="alert">
          <div className="min-w-0 flex-1 text-[13px]">
            <p className="font-medium text-danger">
              {failedNode ? `Failed at ${failedNode}` : "Failed"}
              <span className="ml-2 font-mono text-[11.5px] font-normal">{execution.error.code}</span>
            </p>
            <p className="mt-0.5 text-foreground">{execution.error.message}</p>
          </div>
          {failedStep && selectedId !== failedStep ? (
            <Button variant="secondary" size="sm" onClick={() => setSelection(failedStep)}>
              Show the step
            </Button>
          ) : null}
        </div>
      ) : null}

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_25rem]">
        <div className="min-w-0 space-y-5">
          <Card className="overflow-hidden">
            <CardHeader className="pb-3">
              <div>
                <CardTitle>Graph</CardTitle>
                <CardDescription>Click a node to see what it received and returned.</CardDescription>
              </div>
            </CardHeader>
            {definition.data && types.data ? (
              <ExecutionGraph
                definition={definition.data.definition}
                types={types.data}
                steps={steps}
                runs={runs}
                selectedNode={selected?.node_id ?? null}
                onSelectNode={(nodeId) => {
                  const run = runs.get(nodeId);
                  if (run) setSelection(run.focus.id);
                }}
              />
            ) : (
              <Skeleton className="mx-5 mb-5 h-80" />
            )}
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <div>
                <CardTitle>Timeline</CardTitle>
                <CardDescription>
                  {steps.length} step{steps.length === 1 ? "" : "s"}
                  {execution.steps_truncated ? ", only the first 2,000 shown" : ""}
                </CardDescription>
              </div>
            </CardHeader>
            <Timeline execution={execution} now={query.dataUpdatedAt} selectedStep={selectedId} onSelectStep={setSelection} />
          </Card>

          <Card className="p-5">
            <Tabs defaultValue={execution.status === "succeeded" ? "output" : "trigger"}>
              <TabsList>
                <TabsTrigger value="trigger">Trigger payload</TabsTrigger>
                <TabsTrigger value="output">Output</TabsTrigger>
                <TabsTrigger value="variables">Variables</TabsTrigger>
                <TabsTrigger value="logs">Logs {logs.data ? `(${logs.data.items.length})` : ""}</TabsTrigger>
              </TabsList>
              <TabsContent value="trigger">
                <JsonView value={execution.trigger_payload} label="Trigger payload" empty="The trigger sent no payload." />
              </TabsContent>
              <TabsContent value="output">
                <JsonView value={execution.output} label="Execution output" empty={live ? "Not finished yet." : "No output."} />
              </TabsContent>
              <TabsContent value="variables">
                <JsonView
                  value={Object.keys(execution.variables).length ? execution.variables : null}
                  label="Execution variables"
                  empty="No variables were set in this run."
                />
              </TabsContent>
              <TabsContent value="logs">
                {logs.data ? <LogList lines={logs.data.items} stepNames={stepNames} /> : <Skeleton className="h-40" />}
              </TabsContent>
            </Tabs>
          </Card>
        </div>

        <aside className="lg:sticky lg:top-4 lg:self-start" aria-label="Step details">
          <Card className="overflow-hidden lg:max-h-[calc(100dvh-2rem)] lg:overflow-y-auto">
            {selected ? (
              <StepPanel
                key={selected.id}
                workspace={workspace}
                executionId={execution.id}
                summary={selected}
                nodeType={typeMap.get(selected.node_type)}
                logs={logs.data?.items ?? []}
                onClose={() => setSelection(null)}
              />
            ) : (
              <EmptyState
                icon={steps.length ? <MousePointerClick /> : <Play />}
                title={steps.length ? "Pick a step" : "Waiting to start"}
                description={
                  steps.length
                    ? "Select a node on the graph or a row in the timeline to inspect its input, output and logs."
                    : "The execution is queued. Steps appear here as soon as a worker claims it."
                }
              />
            )}
          </Card>
        </aside>
      </div>
    </PageBody>
  );
}
