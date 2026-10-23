"use client";

import { Background, BackgroundVariant, Controls, ReactFlow } from "@xyflow/react";
import { useMemo } from "react";

import { WorkflowNode } from "@/components/editor/canvas-node";
import { ranNodes, type NodeRun } from "@/lib/executions";
import { toCanvas, type CanvasEdge, type CanvasNode } from "@/lib/graph";
import type { Definition, NodeType, StepSummary } from "@/lib/types";

const nodeTypes = { workflow: WorkflowNode };

/** The graph as it ran: coloured rings for each node's outcome, the taken path highlighted. */
export function ExecutionGraph({
  definition,
  types,
  steps,
  runs,
  selectedNode,
  onSelectNode,
}: {
  definition: Definition;
  types: NodeType[];
  steps: StepSummary[];
  runs: Map<string, NodeRun>;
  selectedNode: string | null;
  onSelectNode: (nodeId: string) => void;
}) {
  const typeMap = useMemo(() => new Map(types.map((t) => [t.type, t])), [types]);
  const base = useMemo(() => toCanvas(definition, typeMap), [definition, typeMap]);
  const ran = useMemo(() => ranNodes(steps), [steps]);

  const nodes: CanvasNode[] = base.nodes.map((node) => {
    const run = runs.get(node.id);
    return {
      ...node,
      selected: node.id === selectedNode,
      // Nodes the run never reached are drawn dashed and quiet; their text keeps full contrast.
      className: run && run.status !== "skipped" ? undefined : "wfe-not-run",
      data: { ...node.data, runStatus: run?.status === "skipped" ? undefined : run?.status },
    };
  });
  const edges: CanvasEdge[] = base.edges.map((edge) => {
    const taken = ran.has(edge.source) && ran.has(edge.target);
    return {
      ...edge,
      animated: false,
      style: taken ? { stroke: "var(--primary)", strokeWidth: 2 } : { opacity: 0.35 },
    };
  });

  return (
    <div className="bg-canvas h-[26rem] rounded-b-xl" data-testid="execution-graph">
      <ReactFlow<CanvasNode, CanvasEdge>
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodeClick={(_, node) => onSelectNode(node.id)}
        nodesDraggable={false}
        nodesConnectable={false}
        deleteKeyCode={null}
        zoomOnScroll={false}
        preventScrolling={false}
        fitView
        // Wide graphs stay legible: below half size the view centres instead of shrinking.
        fitViewOptions={{ padding: 0.12, maxZoom: 1, minZoom: 0.5 }}
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
      </ReactFlow>
    </div>
  );
}
