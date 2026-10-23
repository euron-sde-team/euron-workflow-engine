import { describe, expect, it } from "vitest";

import { defaultFor, fieldTitle, initialConfig, unwrapNullable } from "@/lib/schema";
import type { JsonSchema } from "@/lib/types";

const root: JsonSchema = {
  type: "object",
  required: ["url", "conditions"],
  properties: {
    method: { type: "string", enum: ["GET", "POST"], default: "GET" },
    url: { type: "string" },
    timeout_s: { type: "number", default: 30 },
    credential_id: { anyOf: [{ type: "string", format: "uuid" }, { type: "null" }], default: null },
    conditions: { type: "array", items: { $ref: "#/$defs/Condition" } },
  },
  $defs: { Condition: { type: "object", properties: { left: {} } } },
};

describe("schema helpers", () => {
  it("unwraps nullable fields", () => {
    const { schema, nullable } = unwrapNullable(root.properties!.credential_id!, root);
    expect(nullable).toBe(true);
    expect(schema.type).toBe("string");
  });

  it("builds the starting config of a node", () => {
    expect(initialConfig(root)).toEqual({ method: "GET", url: "", timeout_s: 30, credential_id: null, conditions: [] });
    expect(defaultFor({ type: "integer", minimum: 1 }, root)).toBe(1);
  });

  it("titles fields", () => {
    expect(fieldTitle("credential_id", {})).toBe("Credential");
    expect(fieldTitle("max_rows", { title: "Max Rows" })).toBe("Max rows");
  });
});
