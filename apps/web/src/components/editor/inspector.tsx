"use client";

import { Copy, FlaskConical, Play, Trash2, TriangleAlert, X } from "lucide-react";
import { useMemo, useState } from "react";

import { JsonView } from "@/components/json-view";
import { NodeIcon } from "@/components/node-icon";
import { SchemaForm } from "@/components/editor/schema-form";
import { TriggerInfoBox } from "@/components/editor/trigger-info";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ErrorNotice, Spinner } from "@/components/ui/feedback";
import { FieldHint, Input, Label, NativeSelect, Textarea } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/cn";
import { formatDuration } from "@/lib/format";
import { useTestNode } from "@/lib/queries";
import type {
  Credential,
  Issue,
  NodeSpec,
  NodeTestResult,
  NodeType,
  RetryPolicy,
  TriggerInfo,
} from "@/lib/types";

export type TestContext = {
  input: unknown;
  trigger: unknown;
  steps: Record<string, unknown>;
  vars: Record<string, unknown>;
};

function RetryEditor({
  policy,
  defaults,
  onChange,
  readOnly,
}: {
  policy: RetryPolicy | null | undefined;
  defaults: RetryPolicy;
  onChange: (policy: RetryPolicy | null) => void;
  readOnly: boolean;
}) {
  const custom = Boolean(policy);
  const value = policy ?? defaults;
  const set = (patch: Partial<RetryPolicy>) => onChange({ ...value, ...patch });
  return (
    <div className="border-border space-y-3 rounded-lg border p-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-[13px] font-medium">Retries</p>
          <p className="text-muted-foreground text-xs">
            {custom
              ? `Up to ${value.max_attempts} attempts, backoff from ${value.initial_delay_ms} ms`
              : `Node default: ${defaults.max_attempts} attempt${defaults.max_attempts === 1 ? "" : "s"}`}
          </p>
        </div>
        <Switch
          aria-label="Custom retry policy"
          checked={custom}
          disabled={readOnly}
          onCheckedChange={(checked) =>
            onChange(
              checked ? { ...defaults, max_attempts: Math.max(3, defaults.max_attempts) } : null,
            )
          }
        />
      </div>
      {custom ? (
        <div className="grid grid-cols-2 gap-3">
          {(
            [
              ["max_attempts", "Attempts", 1, 10],
              ["initial_delay_ms", "First delay (ms)", 100, 600000],
              ["max_delay_ms", "Longest delay (ms)", 100, 3600000],
              ["multiplier", "Multiplier", 1, 10],
            ] as const
          ).map(([key, label, min, max]) => (
            <div key={key} className="space-y-1">
              <Label htmlFor={`retry-${key}`}>{label}</Label>
              <Input
                id={`retry-${key}`}
                type="number"
                min={min}
                max={max}
                step={key === "multiplier" ? 0.5 : 1}
                value={value[key]}
                disabled={readOnly}
                onChange={(e) => set({ [key]: Number(e.target.value) } as Partial<RetryPolicy>)}
              />
            </div>
          ))}
          <label className="col-span-2 flex items-center justify-between gap-3 text-[13px]">
            Jitter (spread retries out)
            <Switch
              checked={value.jitter}
              disabled={readOnly}
              onCheckedChange={(jitter) => set({ jitter })}
            />
          </label>
        </div>
      ) : null}
    </div>
  );
}

function TestPanel({
  workspace,
  node,
  nodeType,
  context,
}: {
  workspace: string;
  node: NodeSpec;
  nodeType: NodeType;
  context: TestContext;
}) {
  const test = useTestNode(workspace);
  const [input, setInput] = useState(() => JSON.stringify(context.input ?? {}, null, 2));
  const [parseError, setParseError] = useState<string | null>(null);
  const result: NodeTestResult | undefined = test.data;

  function run() {
    let parsed: unknown;
    try {
      parsed = input.trim() ? JSON.parse(input) : null;
      setParseError(null);
    } catch (exc) {
      setParseError(exc instanceof Error ? exc.message : "Not valid JSON");
      return;
    }
    test.mutate({
      node: { type: node.type, config: node.config, timeout_s: node.timeout_s ?? undefined },
      input: parsed,
      trigger: context.trigger,
      steps: context.steps,
      vars: context.vars,
    });
  }

  return (
    <div className="space-y-4">
      {nodeType.side_effects ? (
        <div className="bg-warning-soft text-warning flex gap-2 rounded-lg px-3 py-2 text-xs">
          <TriangleAlert className="size-4 shrink-0" aria-hidden />
          This node acts on a real system: a test run really sends, writes or publishes.
        </div>
      ) : null}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between gap-2">
          <Label htmlFor="test-input">Input</Label>
          <Button
            type="button"
            variant="link"
            size="sm"
            className="text-xs"
            onClick={() => setInput(JSON.stringify(context.input ?? {}, null, 2))}
          >
            Use the latest data
          </Button>
        </div>
        <Textarea
          id="test-input"
          rows={7}
          className="font-mono text-[12px]"
          value={input}
          spellCheck={false}
          onChange={(e) => setInput(e.target.value)}
        />
        <FieldHint>
          From the latest run of the upstream node when there is one. Templates also see trigger,
          steps and vars.
        </FieldHint>
        {parseError ? <p className="text-danger text-xs">JSON: {parseError}</p> : null}
      </div>
      <Button onClick={run} disabled={test.isPending} className="w-full" data-testid="test-node">
        {test.isPending ? <Spinner className="text-primary-foreground" /> : <FlaskConical />}
        Test this node
      </Button>
      {test.error ? <ErrorNotice message={test.error.message} /> : null}
      {result ? (
        <div className="space-y-3" data-testid="test-result">
          <div className="flex items-center gap-2">
            <Badge tone={result.status === "succeeded" ? "success" : "danger"}>
              {result.status}
            </Badge>
            <span className="text-muted-foreground text-xs">
              {formatDuration(result.duration_ms)}
            </span>
            {result.ports.length ? (
              <span className="text-muted-foreground text-xs">
                output: <span className="font-mono">{result.ports.join(", ")}</span>
              </span>
            ) : null}
          </div>
          {result.error ? (
            <div className="border-danger/30 bg-danger-soft text-danger rounded-lg border px-3 py-2 text-xs">
              <span className="font-mono font-medium">{result.error.code}</span>:{" "}
              {result.error.message}
              {result.error.retryable ? " (would be retried)" : ""}
            </div>
          ) : null}
          {result.status === "succeeded" ? (
            <JsonView value={result.output} label="Output" empty="No output." />
          ) : null}
          {result.events.length ? (
            <div>
              <p className="mb-1 text-xs font-medium">Would publish</p>
              <JsonView value={result.events} />
            </div>
          ) : null}
          {result.logs.length ? (
            <ul className="border-border space-y-1 rounded-lg border p-2 font-mono text-[11.5px]">
              {result.logs.map((line, index) => (
                <li
                  key={index}
                  className={cn(
                    line.level === "warn" && "text-warning",
                    line.level === "error" && "text-danger",
                  )}
                >
                  {line.message}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export function Inspector({
  workspace,
  node,
  nodeType,
  credentials,
  issues,
  readOnly,
  testContext,
  trigger,
  active,
  onChange,
  onDelete,
  onDuplicate,
  onClose,
}: {
  workspace: string;
  node: NodeSpec;
  nodeType: NodeType | undefined;
  credentials: Credential[];
  issues: Issue[];
  readOnly: boolean;
  testContext: TestContext;
  trigger: TriggerInfo | undefined;
  active: boolean;
  onChange: (spec: NodeSpec) => void;
  onDelete: () => void;
  onDuplicate: () => void;
  onClose: () => void;
}) {
  const fieldIssues = useMemo(() => {
    const map = new Map<string, string>();
    for (const issue of issues)
      if (issue.severity === "error") map.set(issue.field ?? "", issue.message);
    return map;
  }, [issues]);
  const general = issues.filter((issue) => !issue.field || issue.field === "name");

  if (!nodeType) {
    return (
      <div className="p-4">
        <ErrorNotice message={`Unknown node type ${node.type}.`} />
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col" data-testid="inspector">
      <div className="border-border flex items-start gap-3 border-b p-4">
        <NodeIcon icon={nodeType.icon} category={nodeType.category} />
        <div className="min-w-0 flex-1">
          <Input
            aria-label="Node name"
            value={node.name}
            disabled={readOnly}
            onChange={(e) => onChange({ ...node, name: e.target.value })}
            className="hover:border-input h-8 border-transparent px-1.5 text-[14px] font-semibold shadow-none"
          />
          <p className="text-muted-foreground mt-0.5 px-1.5 text-xs">
            {nodeType.name} <span className="text-subtle font-mono">steps.{node.id}</span>
          </p>
        </div>
        <Button variant="ghost" size="icon-sm" aria-label="Close inspector" onClick={onClose}>
          <X />
        </Button>
      </div>
      {general.length ? (
        <div className="border-border space-y-1 border-b px-4 py-2">
          {general.map((issue, index) => (
            <p
              key={index}
              className={cn("text-xs", issue.severity === "error" ? "text-danger" : "text-warning")}
            >
              {issue.message}
            </p>
          ))}
        </div>
      ) : null}
      <Tabs defaultValue="configure" className="flex min-h-0 flex-1 flex-col">
        <TabsList className="px-4">
          <TabsTrigger value="configure">Configure</TabsTrigger>
          <TabsTrigger value="settings">Settings</TabsTrigger>
          {!nodeType.is_trigger ? <TabsTrigger value="test">Test</TabsTrigger> : null}
        </TabsList>
        <div className="scroll-quiet min-h-0 flex-1 overflow-y-auto px-4 pb-6">
          <TabsContent value="configure">
            <p className="text-muted-foreground mb-4 text-[12.5px]">{nodeType.description}</p>
            {nodeType.is_trigger ? (
              <TriggerInfoBox node={node} trigger={trigger} active={active} />
            ) : null}
            <SchemaForm
              schema={nodeType.config_schema}
              value={node.config}
              onChange={(config) => onChange({ ...node, config })}
              workspace={workspace}
              credentials={credentials}
              issues={fieldIssues}
              readOnly={readOnly}
            />
          </TabsContent>
          <TabsContent value="settings" className="space-y-4">
            {!nodeType.is_trigger ? (
              <>
                <RetryEditor
                  policy={node.retry}
                  defaults={nodeType.default_retry}
                  readOnly={readOnly}
                  onChange={(retry) => onChange({ ...node, retry })}
                />
                <div className="space-y-1.5">
                  <Label htmlFor="node-timeout">Timeout (seconds)</Label>
                  <Input
                    id="node-timeout"
                    type="number"
                    min={1}
                    max={900}
                    placeholder={String(nodeType.default_timeout_s)}
                    value={node.timeout_s ?? ""}
                    disabled={readOnly}
                    onChange={(e) =>
                      onChange({
                        ...node,
                        timeout_s: e.target.value ? Number(e.target.value) : null,
                      })
                    }
                  />
                  <FieldHint>
                    An attempt that runs longer fails with a timeout and is retried.
                  </FieldHint>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="node-on-error">When it fails</Label>
                  <NativeSelect
                    id="node-on-error"
                    value={node.on_error ?? "fail"}
                    disabled={readOnly}
                    onChange={(e) =>
                      onChange({ ...node, on_error: e.target.value as "fail" | "continue" })
                    }
                  >
                    <option value="fail">Fail the execution (after retries)</option>
                    <option value="continue">Continue with the error as output</option>
                  </NativeSelect>
                </div>
              </>
            ) : null}
            <label className="border-border flex items-center justify-between gap-3 rounded-lg border p-3 text-[13px]">
              <span>
                <span className="block font-medium">Disabled</span>
                <span className="text-muted-foreground block text-xs">
                  {nodeType.is_trigger
                    ? "The trigger stops listening."
                    : "The input passes through unchanged."}
                </span>
              </span>
              <Switch
                checked={Boolean(node.disabled)}
                disabled={readOnly}
                onCheckedChange={(disabled) => onChange({ ...node, disabled })}
              />
            </label>
            <div className="space-y-1.5">
              <Label htmlFor="node-notes">Notes</Label>
              <Textarea
                id="node-notes"
                rows={3}
                value={node.notes ?? ""}
                disabled={readOnly}
                onChange={(e) => onChange({ ...node, notes: e.target.value })}
              />
            </div>
            {!readOnly ? (
              <div className="flex gap-2 pt-2">
                <Button variant="secondary" size="sm" onClick={onDuplicate}>
                  <Copy /> Duplicate
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-danger hover:text-danger"
                  onClick={onDelete}
                >
                  <Trash2 /> Delete node
                </Button>
              </div>
            ) : null}
          </TabsContent>
          {!nodeType.is_trigger ? (
            <TabsContent value="test">
              {readOnly ? (
                <p className="text-muted-foreground text-[13px]">Testing needs the editor role.</p>
              ) : (
                <TestPanel
                  key={node.id}
                  workspace={workspace}
                  node={node}
                  nodeType={nodeType}
                  context={testContext}
                />
              )}
            </TabsContent>
          ) : null}
        </div>
      </Tabs>
      {nodeType.is_trigger && !readOnly ? (
        <div className="border-border text-muted-foreground border-t p-3 text-xs">
          <Play className="mr-1 inline size-3.5" aria-hidden />
          Run the whole workflow from the toolbar to try this trigger with its sample payload.
        </div>
      ) : null}
    </div>
  );
}
