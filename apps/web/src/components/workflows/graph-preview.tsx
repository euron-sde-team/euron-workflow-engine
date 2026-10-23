"use client";

import { Background, BackgroundVariant, ReactFlow } from "@xyflow/react";
import { useMemo } from "react";

import { WorkflowNode } from "@/components/editor/canvas-node";
import { toCanvas, type CanvasEdge, type CanvasNode } from "@/lib/graph";
import type { Definition, NodeType } from "@/lib/types";

const nodeTypes = { workflow: WorkflowNode };

/** A read-only canvas for previews: no dragging, connecting or selecting. */
export function GraphPreview({
  definition,
  types,
  className,
}: {
  definition: Definition;
  types: NodeType[];
  className?: string;
}) {
  const { nodes, edges } = useMemo(
    () => toCanvas(definition, new Map(types.map((t) => [t.type, t]))),
    [definition, types],
  );
  return (
    <div className={className ?? "border-border bg-canvas h-72 rounded-xl border"}>
      <ReactFlow<CanvasNode, CanvasEdge>
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        deleteKeyCode={null}
        zoomOnScroll={false}
        preventScrolling={false}
        fitView
        fitViewOptions={{ padding: 0.15, maxZoom: 0.9 }}
        minZoom={0.1}
        proOptions={{ hideAttribution: true }}
        defaultEdgeOptions={{ type: "smoothstep" }}
      >
        <Background
          variant={BackgroundVariant.Dots}
          gap={18}
          size={1.2}
          color="var(--canvas-dot)"
        />
      </ReactFlow>
    </div>
  );
}
