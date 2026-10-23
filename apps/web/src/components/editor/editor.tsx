"use client";

import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  applyEdgeChanges,
  applyNodeChanges,
  useReactFlow,
  type Connection,
  type EdgeChange,
  type NodeChange,
} from "@xyflow/react";
import {
  ArrowLeft,
  CircleAlert,
  CloudCheck,
  Copy,
  Download,
  History,
  ListChecks,
  Loader2,
  MoreHorizontal,
  PanelLeftClose,
  PanelLeftOpen,
  Play,
  Rocket,
  Settings2,
  Trash2,
  X,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import { toast } from "sonner";

import { WorkflowNode } from "@/components/editor/canvas-node";
import {
  PublishDialog,
  RunDialog,
  SettingsDialog,
  VersionsDialog,
} from "@/components/editor/dialogs";
import { Inspector, type TestContext } from "@/components/editor/inspector";
import { DRAG_TYPE, Palette } from "@/components/editor/palette";
import { StatusBadge, StatusDot } from "@/components/status";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Spinner } from "@/components/ui/feedback";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Switch } from "@/components/ui/switch";
import { Tooltip } from "@/components/ui/tooltip";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatDuration } from "@/lib/format";
import {
  canConnect,
  edgeId,
  nextNodeId,
  nextNodeName,
  outputPorts,
  toCanvas,
  toDefinition,
  type CanvasEdge,
  type CanvasNode,
} from "@/lib/graph";
import {
  exportWorkflow,
  useCredentials,
  useExecution,
  useNodeTypes,
  useSaveDraft,
  useStep,
  useWorkflowActions,
} from "@/lib/queries";
import { initialConfig } from "@/lib/schema";
import type { Execution, Issue, NodeSpec, NodeType, Role, Workflow } from "@/lib/types";

const nodeTypes = { workflow: WorkflowNode };
const AUTOSAVE_MS = 1200;

type SaveState = "saved" | "dirty" | "saving" | "error";

function message(error: unknown): string | null {
  return error instanceof Error ? error.message : null;
}

function latestSteps(execution: Execution | undefined): Map<string, Execution["steps"][number]> {
  const latest = new Map<string, Execution["steps"][number]>();
  for (const step of execution?.steps ?? []) latest.set(step.node_id, step);
  return latest;
}

function EditorCanvas({
  workspace,
  workflow,
  role,
  types,
}: {
  workspace: string;
  workflow: Workflow;
  role: Role;
  types: NodeType[];
}) {
  const router = useRouter();
  const flow = useReactFlow();
  const credentials = useCredentials(workspace);
  const save = useSaveDraft(workspace, workflow.id);
  const actions = useWorkflowActions(workspace, workflow.id);
  const readOnly = role === "viewer";
  const typeMap = useMemo(() => new Map(types.map((t) => [t.type, t])), [types]);

  const [initial] = useState(() => toCanvas(workflow.draft, typeMap));
  const [nodes, setNodes] = useState<CanvasNode[]>(initial.nodes);
  const [edges, setEdges] = useState<CanvasEdge[]>(initial.edges);
  const [generation, setGeneration] = useState(0);
  const [issues, setIssues] = useState<Issue[]>(workflow.issues);
  const [saveState, setSaveState] = useState<SaveState>("saved");
  const [selected, setSelected] = useState<string | null>(null);
  const [palette, setPalette] = useState(true);
  const [dialog, setDialog] = useState<"publish" | "run" | "settings" | "versions" | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const revision = useRef(workflow.draft_revision);
  const version = useRef(0);

  const load = useCallback(
    (source: Workflow) => {
      const canvas = toCanvas(source.draft, typeMap);
      setNodes(canvas.nodes);
      setEdges(canvas.edges);
      setIssues(source.issues);
      setGeneration((g) => g + 1);
      revision.current = source.draft_revision;
      setSaveState("saved");
    },
    [typeMap],
  );

  const touch = useCallback(() => {
    version.current += 1;
    setSaveState("dirty");
  }, []);

  const persist = useCallback(async (): Promise<boolean> => {
    const started = version.current;
    setSaveState("saving");
    try {
      const saved = await save.mutateAsync({
        definition: toDefinition(nodes, edges),
        revision: revision.current,
      });
      revision.current = saved.revision;
      setIssues(saved.issues);
      setSaveState(version.current === started ? "saved" : "dirty");
      return true;
    } catch (error) {
      setSaveState("error");
      if (error instanceof ApiError && error.code === "stale_draft") {
        toast.error("Someone else saved this workflow.", {
          description: "Reload to see their changes; your unsaved edits will be lost.",
          action: { label: "Reload", onClick: () => window.location.reload() },
          duration: 20_000,
        });
      } else {
        toast.error("Could not save the draft", { description: message(error) ?? undefined });
      }
      return false;
    }
  }, [save, nodes, edges]);

  useEffect(() => {
    if (saveState !== "dirty" || readOnly) return;
    const timer = setTimeout(() => void persist(), AUTOSAVE_MS);
    return () => clearTimeout(timer);
  }, [saveState, persist, readOnly, nodes, edges]);

  // Changes that matter to the definition mark the draft dirty; selection and measuring do not.
  const onNodesChange = useCallback(
    (changes: NodeChange<CanvasNode>[]) => {
      const visible = readOnly
        ? changes.filter((c) => c.type === "select" || c.type === "dimensions")
        : changes;
      setNodes((current) => applyNodeChanges(visible, current));
      if (visible.some((c) => c.type === "remove" || (c.type === "position" && !c.dragging)))
        touch();
      const removed = visible.filter((c) => c.type === "remove").map((c) => c.id);
      if (removed.length) {
        setEdges((current) =>
          current.filter((e) => !removed.includes(e.source) && !removed.includes(e.target)),
        );
        if (selected && removed.includes(selected)) setSelected(null);
      }
    },
    [readOnly, touch, selected],
  );

  const onEdgesChange = useCallback(
    (changes: EdgeChange<CanvasEdge>[]) => {
      const visible = readOnly ? changes.filter((c) => c.type === "select") : changes;
      setEdges((current) => applyEdgeChanges(visible, current));
      if (visible.some((c) => c.type === "remove")) touch();
    },
    [readOnly, touch],
  );

  const isValidConnection = useCallback(
    (connection: Connection | CanvasEdge) =>
      canConnect(
        nodes.find((n) => n.id === connection.source),
        nodes.find((n) => n.id === connection.target),
        connection.targetHandle,
        edges,
      ),
    [nodes, edges],
  );

  const onConnect = useCallback(
    (connection: Connection) => {
      if (readOnly || !isValidConnection(connection)) return;
      const sourcePort = connection.sourceHandle ?? "main";
      const targetPort = connection.targetHandle ?? "main";
      setEdges((current) => [
        ...current,
        {
          id: edgeId(connection.source, sourcePort, connection.target, targetPort),
          source: connection.source,
          target: connection.target,
          sourceHandle: sourcePort,
          targetHandle: targetPort,
          animated: targetPort === "loop",
        },
      ]);
      touch();
    },
    [readOnly, isValidConnection, touch],
  );

  const addNode = useCallback(
    (type: NodeType, position?: { x: number; y: number }) => {
      if (readOnly) return;
      const anchor = nodes.find((n) => n.id === selected);
      const id = nextNodeId(
        type.type,
        nodes.map((n) => n.id),
      );
      const spec: NodeSpec = {
        id,
        type: type.type,
        name: nextNodeName(
          type.name,
          nodes.map((n) => n.data.spec.name),
        ),
        config: initialConfig(type.config_schema),
        position:
          position ??
          (anchor
            ? { x: anchor.position.x + 280, y: anchor.position.y }
            : flow.screenToFlowPosition({ x: window.innerWidth / 2, y: window.innerHeight / 2 })),
      };
      setNodes((current) => [
        ...current.map((n) => ({ ...n, selected: false })),
        {
          id,
          type: "workflow",
          position: spec.position,
          selected: true,
          data: { spec, nodeType: type, issues: 0, warnings: 0 },
        },
      ]);
      // Adding after a selected node connects them, the way people build a flow left to right.
      if (anchor && !position && !type.is_trigger) {
        const port = outputPorts(anchor.data.spec, anchor.data.nodeType)[0];
        if (port) {
          setEdges((current) => [
            ...current,
            {
              id: edgeId(anchor.id, port, id, "main"),
              source: anchor.id,
              target: id,
              sourceHandle: port,
              targetHandle: "main",
            },
          ]);
        }
      }
      setSelected(id);
      touch();
    },
    [readOnly, nodes, selected, flow, touch],
  );

  const updateSpec = useCallback(
    (spec: NodeSpec) => {
      setNodes((current) =>
        current.map((n) => (n.id === spec.id ? { ...n, data: { ...n.data, spec } } : n)),
      );
      touch();
    },
    [touch],
  );

  const removeNode = useCallback(
    (id: string) => {
      setNodes((current) => current.filter((n) => n.id !== id));
      setEdges((current) => current.filter((e) => e.source !== id && e.target !== id));
      setSelected(null);
      touch();
    },
    [touch],
  );

  const duplicateNode = useCallback(
    (id: string) => {
      const source = nodes.find((n) => n.id === id);
      if (!source) return;
      const newId = nextNodeId(
        source.data.spec.type,
        nodes.map((n) => n.id),
      );
      const spec: NodeSpec = {
        ...structuredClone(source.data.spec),
        id: newId,
        name: nextNodeName(
          source.data.spec.name,
          nodes.map((n) => n.data.spec.name),
        ),
        position: { x: source.position.x + 40, y: source.position.y + 120 },
      };
      setNodes((current) => [
        ...current,
        { id: newId, type: "workflow", position: spec.position, data: { ...source.data, spec } },
      ]);
      setSelected(newId);
      touch();
    },
    [nodes, touch],
  );

  function onDrop(event: DragEvent) {
    event.preventDefault();
    const typeName = event.dataTransfer.getData(DRAG_TYPE);
    const type = typeMap.get(typeName);
    if (type) addNode(type, flow.screenToFlowPosition({ x: event.clientX, y: event.clientY }));
  }

  // Test runs: poll the execution and paint each node with its latest step status.
  const run = useExecution(workspace, runId);
  const steps = useMemo(() => latestSteps(run.data), [run.data]);

  const errorsByNode = useMemo(() => {
    const counts = new Map<string, { errors: number; warnings: number }>();
    for (const issue of issues) {
      if (!issue.node_id) continue;
      const entry = counts.get(issue.node_id) ?? { errors: 0, warnings: 0 };
      if (issue.severity === "error") entry.errors += 1;
      else entry.warnings += 1;
      counts.set(issue.node_id, entry);
    }
    return counts;
  }, [issues]);

  const rendered = useMemo(
    () =>
      nodes.map((node) => {
        const counts = errorsByNode.get(node.id);
        return {
          ...node,
          data: {
            ...node.data,
            issues: counts?.errors ?? 0,
            warnings: counts?.warnings ?? 0,
            runStatus: runId ? steps.get(node.id)?.status : undefined,
          },
        };
      }),
    [nodes, errorsByNode, steps, runId],
  );

  const selectedNode = nodes.find((n) => n.id === selected);
  const errors = issues.filter((i) => i.severity === "error");
  const triggers = nodes.map((n) => n.data.spec).filter((spec) => spec.type.startsWith("trigger."));

  // Sample data for the inspector's test tab: the latest output of the node feeding this one.
  const upstream = selected
    ? edges.find((e) => e.target === selected && (e.targetHandle ?? "main") === "main")?.source
    : undefined;
  const upstreamStep = upstream && runId ? steps.get(upstream) : undefined;
  const upstreamDetail = useStep(workspace, runId ?? "none", upstreamStep?.id ?? null);
  const testContext: TestContext = useMemo(() => {
    const triggerSample = triggers[0]?.config.sample_payload ?? {};
    const upstreamType = upstream
      ? typeMap.get(nodes.find((n) => n.id === upstream)?.data.spec.type ?? "")
      : undefined;
    const input =
      upstreamDetail.data?.output ??
      (upstreamType?.is_trigger ? triggerSample : (upstreamType?.sample_output ?? triggerSample));
    return {
      input,
      trigger: run.data?.trigger_payload ?? triggerSample,
      steps: upstream && upstreamDetail.data ? { [upstream]: upstreamDetail.data.output } : {},
      vars: run.data?.variables ?? {},
    };
  }, [triggers, upstream, typeMap, nodes, upstreamDetail.data, run.data]);

  async function startRun(triggerId: string, payload: unknown) {
    if (saveState !== "saved" && !(await persist())) return;
    try {
      const started = await actions.run.mutateAsync({
        use_draft: true,
        trigger_node: triggerId,
        payload,
      });
      setRunId(started.execution_id);
      setDialog(null);
      toast.success("Test run started");
    } catch {
      // Shown in the dialog.
    }
  }

  async function publish(note: string, activate: boolean) {
    if (saveState !== "saved" && !(await persist())) return;
    try {
      const updated = await actions.publish.mutateAsync({ note, activate });
      setDialog(null);
      toast.success(`Published version ${updated.published_version}`, {
        description: updated.active ? "The workflow is active." : "The workflow is not active.",
      });
    } catch {
      // Shown in the dialog.
    }
  }

  async function toggleActive(active: boolean) {
    try {
      await (active ? actions.activate : actions.deactivate).mutateAsync();
      toast.success(active ? "Workflow activated" : "Workflow deactivated");
    } catch (error) {
      toast.error(message(error) ?? "Could not change the workflow");
    }
  }

  async function download() {
    const document = await exportWorkflow(workspace, workflow.id);
    const blob = new Blob([JSON.stringify(document, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = Object.assign(window.document.createElement("a"), {
      href: url,
      download: `${workflow.name.toLowerCase().replace(/[^a-z0-9]+/g, "-")}.json`,
    });
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="border-border bg-card flex flex-wrap items-center gap-2 border-b px-3 py-2">
        <Button asChild variant="ghost" size="icon-sm" aria-label="Back to workflows">
          <Link href={`/w/${workspace}/workflows`}>
            <ArrowLeft />
          </Link>
        </Button>
        <div className="min-w-0">
          <h1
            className="truncate text-[15px] font-semibold tracking-tight"
            data-testid="workflow-name"
          >
            {workflow.name}
          </h1>
          <div className="text-muted-foreground flex items-center gap-2 text-[11.5px]">
            {workflow.published_version ? (
              <span>Version {workflow.published_version}</span>
            ) : (
              <span>Never published</span>
            )}
            {workflow.has_unpublished_changes && workflow.published_version ? (
              <Badge tone="warning">Unpublished changes</Badge>
            ) : null}
            <span className="flex items-center gap-1" data-testid="save-state">
              {saveState === "saving" ? (
                <>
                  <Loader2 className="size-3 animate-spin" /> Saving
                </>
              ) : saveState === "dirty" ? (
                "Unsaved changes"
              ) : saveState === "error" ? (
                <span className="text-danger">Not saved</span>
              ) : (
                <>
                  <CloudCheck className="size-3" /> Saved
                </>
              )}
            </span>
          </div>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="secondary" size="sm" data-testid="issues-button">
                {errors.length ? (
                  <CircleAlert className="text-danger" />
                ) : (
                  <ListChecks className="text-success" />
                )}
                {errors.length
                  ? `${errors.length} problem${errors.length === 1 ? "" : "s"}`
                  : "No problems"}
              </Button>
            </PopoverTrigger>
            <PopoverContent align="end" className="w-96">
              {issues.length === 0 ? (
                <p className="text-muted-foreground text-[13px]">
                  The workflow is ready to publish.
                </p>
              ) : (
                <ul className="max-h-80 space-y-1 overflow-y-auto">
                  {issues.map((issue, index) => (
                    <li key={index}>
                      <button
                        type="button"
                        className="hover:bg-muted flex w-full gap-2 rounded-md px-2 py-1.5 text-left text-[12.5px]"
                        onClick={() => issue.node_id && setSelected(issue.node_id)}
                      >
                        <CircleAlert
                          className={cn(
                            "mt-0.5 size-3.5 shrink-0",
                            issue.severity === "error" ? "text-danger" : "text-warning",
                          )}
                          aria-hidden
                        />
                        <span>
                          {issue.node_id ? (
                            <span className="font-medium">
                              {nodes.find((n) => n.id === issue.node_id)?.data.spec.name ??
                                issue.node_id}
                              :{" "}
                            </span>
                          ) : null}
                          {issue.message}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </PopoverContent>
          </Popover>
          {!readOnly ? (
            <>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setDialog("run")}
                data-testid="run-draft"
              >
                <Play /> Run
              </Button>
              <Button size="sm" onClick={() => setDialog("publish")} data-testid="publish">
                <Rocket /> Publish
              </Button>
            </>
          ) : null}
          <Tooltip content={workflow.published_version ? "Listen to triggers" : "Publish first"}>
            <label className="border-border flex items-center gap-2 rounded-lg border px-2.5 py-1 text-[12.5px]">
              Active
              <Switch
                checked={workflow.active}
                disabled={
                  readOnly ||
                  !workflow.published_version ||
                  actions.activate.isPending ||
                  actions.deactivate.isPending
                }
                onCheckedChange={(checked) => void toggleActive(checked)}
                aria-label="Active"
              />
            </label>
          </Tooltip>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon-sm" aria-label="More actions">
                <MoreHorizontal />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => setDialog("versions")}>
                <History /> Versions
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => setDialog("settings")} disabled={readOnly}>
                <Settings2 /> Settings
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => void download()}>
                <Download /> Export JSON
              </DropdownMenuItem>
              <DropdownMenuItem
                disabled={readOnly}
                onSelect={async () => {
                  const copy = await actions.duplicate.mutateAsync();
                  router.push(`/w/${workspace}/workflows/${copy.id}`);
                }}
              >
                <Copy /> Duplicate
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                destructive
                disabled={readOnly}
                onSelect={async () => {
                  if (!window.confirm(`Delete "${workflow.name}" and its history?`)) return;
                  await actions.remove.mutateAsync();
                  router.replace(`/w/${workspace}/workflows`);
                }}
              >
                <Trash2 /> Delete workflow
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        {!readOnly && palette ? (
          <aside
            className="border-border bg-sidebar hidden w-64 shrink-0 border-r md:block"
            aria-label="Nodes"
          >
            <Palette types={types} onAdd={(type) => addNode(type)} />
          </aside>
        ) : null}
        <div
          className="relative min-w-0 flex-1"
          onDragOver={(e) => e.preventDefault()}
          onDrop={onDrop}
          data-testid="canvas"
        >
          <ReactFlow<CanvasNode, CanvasEdge>
            nodes={rendered}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            isValidConnection={isValidConnection}
            onNodeClick={(_, node) => setSelected(node.id)}
            onPaneClick={() => setSelected(null)}
            nodesDraggable={!readOnly}
            nodesConnectable={!readOnly}
            deleteKeyCode={readOnly ? null : ["Backspace", "Delete"]}
            fitView
            fitViewOptions={{ padding: 0.25, maxZoom: 1.1 }}
            minZoom={0.2}
            proOptions={{ hideAttribution: true }}
            defaultEdgeOptions={{ type: "smoothstep" }}
          >
            <Background
              variant={BackgroundVariant.Dots}
              gap={18}
              size={1.2}
              color="var(--canvas-dot)"
            />
            <Controls showInteractive={false} position="bottom-left" />
            <MiniMap
              pannable
              zoomable
              position="bottom-right"
              className="!hidden lg:!block"
              ariaLabel="Minimap"
            />
          </ReactFlow>
          {!readOnly ? (
            <Button
              variant="secondary"
              size="icon-sm"
              className="absolute top-3 left-3 hidden md:inline-flex"
              aria-label={palette ? "Hide nodes" : "Show nodes"}
              onClick={() => setPalette((p) => !p)}
            >
              {palette ? <PanelLeftClose /> : <PanelLeftOpen />}
            </Button>
          ) : null}
          {runId && run.data ? (
            <div
              className="border-border bg-card absolute inset-x-3 bottom-3 z-10 mx-auto max-w-xl rounded-xl border p-3 shadow-md lg:right-[13rem]"
              data-testid="run-panel"
            >
              <div className="flex items-center gap-2">
                <StatusBadge status={run.data.status} />
                <span className="text-muted-foreground text-[12.5px]">
                  Test run{" "}
                  {run.data.duration_ms !== null
                    ? `in ${formatDuration(run.data.duration_ms)}`
                    : "in progress"}
                </span>
                <Link
                  href={`/w/${workspace}/executions/${run.data.id}`}
                  className="text-primary ml-auto text-[12.5px] font-medium hover:underline"
                >
                  Open execution
                </Link>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Close run panel"
                  onClick={() => setRunId(null)}
                >
                  <X />
                </Button>
              </div>
              {run.data.error ? (
                <p className="bg-danger-soft text-danger mt-2 rounded-md px-2 py-1 text-xs">
                  <span className="font-mono">{run.data.error.code}</span>: {run.data.error.message}
                </p>
              ) : null}
              <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
                {[...steps.values()].map((step) => (
                  <button
                    key={step.id}
                    type="button"
                    className="text-muted-foreground hover:text-foreground flex items-center gap-1.5 text-[12px]"
                    onClick={() => setSelected(step.node_id)}
                  >
                    <StatusDot status={step.status} />
                    {step.node_name}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
        </div>
        {selectedNode ? (
          <aside
            className="border-border bg-card fixed inset-0 z-30 w-full border-l md:static md:z-auto md:w-[24rem] md:shrink-0"
            aria-label="Node settings"
          >
            <Inspector
              key={`${selectedNode.id}:${generation}`}
              workspace={workspace}
              node={selectedNode.data.spec}
              nodeType={typeMap.get(selectedNode.data.spec.type)}
              credentials={credentials.data ?? []}
              issues={issues.filter((i) => i.node_id === selectedNode.id)}
              readOnly={readOnly}
              testContext={testContext}
              trigger={workflow.triggers.find((t) => t.node_id === selectedNode.id)}
              active={workflow.active}
              onChange={updateSpec}
              onDelete={() => removeNode(selectedNode.id)}
              onDuplicate={() => duplicateNode(selectedNode.id)}
              onClose={() => setSelected(null)}
            />
          </aside>
        ) : null}
      </div>

      <PublishDialog
        open={dialog === "publish"}
        onOpenChange={(open) => setDialog(open ? "publish" : null)}
        workflow={workflow}
        errors={errors}
        pending={actions.publish.isPending || save.isPending}
        error={message(actions.publish.error)}
        onPublish={(note, activate) => void publish(note, activate)}
      />
      <RunDialog
        open={dialog === "run"}
        onOpenChange={(open) => setDialog(open ? "run" : null)}
        triggers={triggers}
        pending={actions.run.isPending || save.isPending}
        error={message(actions.run.error)}
        onRun={(trigger, payload) => void startRun(trigger, payload)}
      />
      <SettingsDialog
        open={dialog === "settings"}
        onOpenChange={(open) => setDialog(open ? "settings" : null)}
        workflow={workflow}
        pending={actions.update.isPending}
        error={message(actions.update.error)}
        onSave={async (body) => {
          await actions.update.mutateAsync(body);
          setDialog(null);
          toast.success("Settings saved");
        }}
      />
      <VersionsDialog
        open={dialog === "versions"}
        onOpenChange={(open) => setDialog(open ? "versions" : null)}
        workspace={workspace}
        workflowId={workflow.id}
        readOnly={readOnly}
        pending={actions.restore.isPending}
        onRestore={async (number) => {
          const restored = await actions.restore.mutateAsync(number);
          load(restored);
          setDialog(null);
          toast.success(`Version ${number} copied into the draft`);
        }}
      />
    </div>
  );
}

export function WorkflowEditor(props: { workspace: string; workflow: Workflow; role: Role }) {
  const types = useNodeTypes();
  if (!types.data) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner className="size-5" />
      </div>
    );
  }
  return (
    <ReactFlowProvider>
      <EditorCanvas {...props} types={types.data} />
    </ReactFlowProvider>
  );
}
