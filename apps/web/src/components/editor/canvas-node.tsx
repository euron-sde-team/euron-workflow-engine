"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";
import { CircleAlert, PowerOff } from "lucide-react";
import { memo } from "react";

import { NodeIcon } from "@/components/node-icon";
import { StatusDot } from "@/components/status";
import { cn } from "@/lib/cn";
import { outputPorts, portLabel, type CanvasNode } from "@/lib/graph";
import type { StepStatus } from "@/lib/types";

const RUN_RING: Record<string, string> = {
  succeeded: "ring-2 ring-success/60",
  failed: "ring-2 ring-danger/70",
  running: "ring-2 ring-info/70",
  waiting: "ring-2 ring-warning/70",
  queued: "ring-2 ring-input",
};

function WorkflowNodeView({ data, selected }: NodeProps<CanvasNode>) {
  const { spec, nodeType, issues, warnings, runStatus } = data;
  const inputs = nodeType?.inputs ?? ["main"];
  const ports = outputPorts(spec, nodeType);
  const many = ports.length > 1;
  return (
    <div
      className={cn(
        "bg-card text-card-foreground relative w-56 rounded-xl border shadow-sm transition-shadow",
        selected ? "border-primary shadow-md" : "border-border",
        issues > 0 && !selected && "border-danger/60",
        spec.disabled && "opacity-60",
        runStatus && RUN_RING[runStatus],
      )}
      data-testid={`node-${spec.id}`}
    >
      {inputs.includes("main") ? (
        <Handle type="target" position={Position.Left} id="main" className="!size-3 !border-2" />
      ) : null}
      {inputs.includes("loop") ? (
        <Handle
          type="target"
          position={Position.Bottom}
          id="loop"
          className="!border-info !size-3 !border-2"
          title="Connect the end of the loop body here"
        />
      ) : null}
      <div className="flex items-center gap-2.5 px-3 py-2.5">
        <NodeIcon icon={nodeType?.icon ?? "blocks"} category={nodeType?.category} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13px] leading-tight font-semibold">{spec.name}</p>
          <p className="text-muted-foreground truncate text-[11px]">
            {nodeType?.name ?? spec.type}
          </p>
        </div>
        {runStatus ? <StatusDot status={runStatus as StepStatus} /> : null}
        {spec.disabled ? <PowerOff className="text-subtle size-3.5" aria-label="Disabled" /> : null}
        {issues > 0 ? (
          <span
            className="text-danger flex items-center gap-0.5 text-[11px] font-medium"
            title={`${issues} problem(s)`}
          >
            <CircleAlert className="size-3.5" aria-hidden />
            {issues}
          </span>
        ) : warnings > 0 ? (
          <CircleAlert className="text-warning size-3.5" aria-label={`${warnings} warning(s)`} />
        ) : null}
      </div>
      {many ? (
        <div className="border-border border-t px-3 py-1.5">
          {ports.map((port) => (
            <div
              key={port}
              className="text-muted-foreground relative flex h-5 items-center justify-end text-[11px]"
            >
              {portLabel(port, nodeType)}
              <Handle
                type="source"
                position={Position.Right}
                id={port}
                className="!-right-[18px] !size-3 !border-2"
                style={{ top: "50%" }}
              />
            </div>
          ))}
        </div>
      ) : ports.length === 1 ? (
        <Handle
          type="source"
          position={Position.Right}
          id={ports[0]}
          className="!size-3 !border-2"
        />
      ) : null}
    </div>
  );
}

export const WorkflowNode = memo(WorkflowNodeView);
