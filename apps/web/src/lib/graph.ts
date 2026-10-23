import type { Edge, Node } from "@xyflow/react";

import type { Definition, EdgeSpec, NodeSpec, NodeType } from "@/lib/types";

export type CanvasNodeData = {
  spec: NodeSpec;
  nodeType: NodeType | undefined;
  issues: number;
  warnings: number;
  runStatus?: string;
};

export type CanvasNode = Node<CanvasNodeData, "workflow">;
export type CanvasEdge = Edge;

/** Output ports of a node; switch nodes derive theirs from their cases. */
export function outputPorts(
  spec: Pick<NodeSpec, "type" | "config">,
  nodeType: NodeType | undefined,
): string[] {
  if (!nodeType) return ["main"];
  if (nodeType.dynamic_ports) {
    const cases = Array.isArray(spec.config.cases)
      ? (spec.config.cases as { port?: unknown }[])
      : [];
    const ports = cases.map((c) => (typeof c.port === "string" ? c.port : "")).filter(Boolean);
    if (spec.config.fallback !== false) ports.push("default");
    return [...new Set(ports)];
  }
  return nodeType.ports;
}

export function portLabel(port: string, nodeType: NodeType | undefined): string {
  return nodeType?.port_labels[port] ?? port.replace(/_/g, " ");
}

/** A readable, unique id for a new node: http_request, http_request_2, ... */
export function nextNodeId(type: string, taken: Iterable<string>): string {
  const base =
    (type.split(".").at(-1) ?? "node").replace(/[^a-z0-9_]/g, "_").replace(/^[^a-z]+/, "") ||
    "node";
  const used = new Set(taken);
  if (!used.has(base)) return base;
  for (let index = 2; ; index += 1) {
    const candidate = `${base}_${index}`;
    if (!used.has(candidate)) return candidate;
  }
}

export function nextNodeName(name: string, taken: Iterable<string>): string {
  const used = new Set([...taken].map((n) => n.toLowerCase()));
  if (!used.has(name.toLowerCase())) return name;
  for (let index = 2; ; index += 1) {
    const candidate = `${name} ${index}`;
    if (!used.has(candidate.toLowerCase())) return candidate;
  }
}

export function edgeId(
  source: string,
  sourcePort: string,
  target: string,
  targetPort: string,
): string {
  return `${source}-${sourcePort}-${target}-${targetPort}`;
}

/** Nodes without a stored position (imports, API-built workflows) get a left-to-right layout. */
export function layout(definition: Definition): Definition {
  if (definition.nodes.every((n) => n.position && (n.position.x !== 0 || n.position.y !== 0)))
    return definition;
  const incoming = new Map<string, number>();
  for (const node of definition.nodes) incoming.set(node.id, 0);
  for (const edge of definition.edges)
    incoming.set(edge.target, (incoming.get(edge.target) ?? 0) + 1);
  const depth = new Map<string, number>();
  const queue = definition.nodes.filter((n) => (incoming.get(n.id) ?? 0) === 0).map((n) => n.id);
  for (const id of queue) depth.set(id, 0);
  while (queue.length) {
    const id = queue.shift()!;
    for (const edge of definition.edges.filter(
      (e) => e.source === id && e.target_port !== "loop",
    )) {
      const next = (depth.get(id) ?? 0) + 1;
      if (next > (depth.get(edge.target) ?? -1)) {
        depth.set(edge.target, next);
        queue.push(edge.target);
      }
    }
  }
  const rows = new Map<number, number>();
  return {
    ...definition,
    nodes: definition.nodes.map((node) => {
      const column = depth.get(node.id) ?? 0;
      const row = rows.get(column) ?? 0;
      rows.set(column, row + 1);
      return { ...node, position: { x: column * 280, y: row * 150 } };
    }),
  };
}

export function toCanvas(
  definition: Definition,
  types: Map<string, NodeType>,
): { nodes: CanvasNode[]; edges: CanvasEdge[] } {
  const placed = layout(definition);
  return {
    nodes: placed.nodes.map((spec) => ({
      id: spec.id,
      type: "workflow",
      position: spec.position,
      data: { spec, nodeType: types.get(spec.type), issues: 0, warnings: 0 },
    })),
    edges: placed.edges.map(toCanvasEdge),
  };
}

export function toCanvasEdge(edge: EdgeSpec): CanvasEdge {
  return {
    id: edge.id,
    source: edge.source,
    target: edge.target,
    sourceHandle: edge.source_port,
    targetHandle: edge.target_port,
    animated: edge.target_port === "loop",
  };
}

export function toDefinition(nodes: CanvasNode[], edges: CanvasEdge[]): Definition {
  return {
    schema_version: 1,
    nodes: nodes.map((node) => ({
      ...node.data.spec,
      position: { x: Math.round(node.position.x), y: Math.round(node.position.y) },
    })),
    edges: edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      source_port: edge.sourceHandle ?? "main",
      target: edge.target,
      target_port: edge.targetHandle ?? "main",
    })),
  };
}

/** Whether a connection makes sense before the server sees it. */
export function canConnect(
  source: CanvasNode | undefined,
  target: CanvasNode | undefined,
  targetPort: string | null | undefined,
  edges: CanvasEdge[],
): boolean {
  if (!source || !target || source.id === target.id) return false;
  if (target.data.nodeType?.is_trigger) return false;
  if (targetPort === "loop" && target.data.spec.type !== "flow.loop") return false;
  return !edges.some(
    (edge) =>
      edge.source === source.id &&
      edge.target === target.id &&
      (edge.targetHandle ?? "main") === (targetPort ?? "main"),
  );
}
