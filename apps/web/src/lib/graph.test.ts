import { describe, expect, it } from "vitest";

import {
  canConnect,
  layout,
  nextNodeId,
  nextNodeName,
  outputPorts,
  toCanvas,
  toDefinition,
  type CanvasNode,
} from "@/lib/graph";
import type { Definition, NodeType } from "@/lib/types";

const type = (overrides: Partial<NodeType>): NodeType =>
  ({
    type: "core.transform",
    name: "Transform",
    category: "core",
    description: "",
    icon: "shuffle",
    is_trigger: false,
    inputs: ["main"],
    ports: ["main"],
    port_labels: {},
    dynamic_ports: false,
    side_effects: false,
    default_retry: {
      max_attempts: 1,
      initial_delay_ms: 1000,
      max_delay_ms: 60000,
      multiplier: 2,
      jitter: true,
    },
    default_timeout_s: 30,
    template_fields: [],
    credential_fields: {},
    config_schema: {},
    sample_output: null,
    ...overrides,
  }) as NodeType;

const definition: Definition = {
  schema_version: 1,
  nodes: [
    { id: "start", type: "trigger.manual", name: "Start", config: {}, position: { x: 0, y: 0 } },
    { id: "check", type: "flow.if", name: "Check", config: {}, position: { x: 0, y: 0 } },
    { id: "yes", type: "core.transform", name: "Yes", config: {}, position: { x: 0, y: 0 } },
  ],
  edges: [
    { id: "e1", source: "start", source_port: "main", target: "check", target_port: "main" },
    { id: "e2", source: "check", source_port: "true", target: "yes", target_port: "main" },
  ],
};

describe("ports and ids", () => {
  it("derives switch ports from its cases", () => {
    const switchType = type({ type: "flow.switch", dynamic_ports: true, ports: ["default"] });
    const config = { cases: [{ port: "high" }, { port: "low" }], fallback: true };
    expect(outputPorts({ type: "flow.switch", config }, switchType)).toEqual([
      "high",
      "low",
      "default",
    ]);
    expect(
      outputPorts({ type: "flow.switch", config: { ...config, fallback: false } }, switchType),
    ).toEqual(["high", "low"]);
    expect(
      outputPorts({ type: "flow.if", config: {} }, type({ ports: ["true", "false"] })),
    ).toEqual(["true", "false"]);
  });

  it("makes readable unique ids and names", () => {
    expect(nextNodeId("http.request", [])).toBe("request");
    expect(nextNodeId("http.request", ["request", "request_2"])).toBe("request_3");
    expect(nextNodeId("aws.s3_put", [])).toBe("s3_put");
    expect(nextNodeName("Transform", ["transform"])).toBe("Transform 2");
  });
});

describe("layout and conversion", () => {
  it("lays out unplaced nodes by depth", () => {
    const placed = layout(definition);
    expect(placed.nodes.map((n) => n.position.x)).toEqual([0, 280, 560]);
  });

  it("round-trips through the canvas", () => {
    const types = new Map([["flow.if", type({ type: "flow.if", ports: ["true", "false"] })]]);
    const canvas = toCanvas(definition, types);
    expect(canvas.edges[1]).toMatchObject({ sourceHandle: "true", targetHandle: "main" });
    const back = toDefinition(canvas.nodes, canvas.edges);
    expect(back.edges).toEqual(definition.edges);
    expect(back.nodes.map((n) => n.id)).toEqual(["start", "check", "yes"]);
  });

  it("refuses connections into triggers, duplicates and self-loops", () => {
    const types = new Map([
      ["trigger.manual", type({ type: "trigger.manual", is_trigger: true, inputs: [] })],
      ["core.transform", type({})],
    ]);
    const { nodes, edges } = toCanvas(definition, types);
    const byId = (id: string) => nodes.find((n) => n.id === id) as CanvasNode;
    expect(canConnect(byId("yes"), byId("start"), "main", edges)).toBe(false);
    expect(canConnect(byId("start"), byId("check"), "main", edges)).toBe(false);
    expect(canConnect(byId("yes"), byId("yes"), "main", edges)).toBe(false);
    expect(canConnect(byId("start"), byId("yes"), "main", edges)).toBe(true);
    expect(canConnect(byId("start"), byId("yes"), "loop", edges)).toBe(false);
  });
});
