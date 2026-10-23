import type { JsonSchema } from "@/lib/types";

/** Follow a local `$ref` ("#/$defs/Name") into the root schema's definitions. */
export function resolveRef(schema: JsonSchema, root: JsonSchema): JsonSchema {
  if (!schema.$ref) return schema;
  const name = schema.$ref.split("/").at(-1) ?? "";
  const target = root.$defs?.[name];
  return target ? { ...target, ...schema, $ref: undefined } : schema;
}

/** Pydantic writes `X | None` as anyOf [X, null]; editors want X and a "nullable" flag. */
export function unwrapNullable(
  schema: JsonSchema,
  root: JsonSchema,
): { schema: JsonSchema; nullable: boolean } {
  const resolved = resolveRef(schema, root);
  const options = resolved.anyOf;
  if (!options) return { schema: resolved, nullable: false };
  const concrete = options.filter((option) => option.type !== "null");
  const nullable = concrete.length !== options.length;
  if (concrete.length === 1) {
    const { anyOf: _anyOf, ...rest } = resolved;
    void _anyOf;
    return { schema: { ...resolveRef(concrete[0]!, root), ...rest, anyOf: undefined }, nullable };
  }
  return { schema: resolved, nullable };
}

export function schemaType(schema: JsonSchema): string | undefined {
  if (Array.isArray(schema.type)) return schema.type.find((t) => t !== "null");
  return schema.type;
}

/** A starting value for a field: its default, or an empty value of its type. */
export function defaultFor(schema: JsonSchema, root: JsonSchema): unknown {
  const { schema: field } = unwrapNullable(schema, root);
  if (field.default !== undefined) return structuredClone(field.default);
  if (field.enum?.length) return field.enum[0];
  switch (schemaType(field)) {
    case "string":
      return "";
    case "integer":
    case "number":
      return field.minimum ?? 0;
    case "boolean":
      return false;
    case "array":
      return [];
    case "object":
      return {};
    default:
      return null;
  }
}

/** The config a new node starts with: required fields get a value, optional ones their default. */
export function initialConfig(root: JsonSchema): Record<string, unknown> {
  const config: Record<string, unknown> = {};
  const required = new Set(root.required ?? []);
  for (const [name, field] of Object.entries(root.properties ?? {})) {
    const { schema } = unwrapNullable(field, root);
    if (schema.default !== undefined) config[name] = structuredClone(schema.default);
    else if (required.has(name)) config[name] = defaultFor(field, root);
  }
  return config;
}

export function fieldTitle(name: string, schema: JsonSchema): string {
  if (schema.title && schema.title.toLowerCase() !== name.replace(/_/g, " ")) return schema.title;
  const words = name.replace(/_id$/, "").split("_");
  const label = words.join(" ");
  return label.charAt(0).toUpperCase() + label.slice(1);
}
