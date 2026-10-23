"use client";

import { Braces, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { FieldHint, Input, Label, NativeSelect, Textarea } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/cn";
import { formatDateTime } from "@/lib/format";
import { useCronPreview } from "@/lib/queries";
import { defaultFor, fieldTitle, resolveRef, schemaType, unwrapNullable } from "@/lib/schema";
import type { Credential, JsonSchema } from "@/lib/types";

type FormContext = {
  root: JsonSchema;
  workspace: string;
  credentials: Credential[];
  issues: Map<string, string>;
  readOnly: boolean;
};

const mono = "font-mono text-[12.5px]";

function issueFor(issues: Map<string, string>, path: string): string | undefined {
  for (const [field, message] of issues) {
    if (field === path || field.startsWith(`${path}.`) || field.startsWith(`${path}[`))
      return message;
  }
  return undefined;
}

function FieldShell({
  id,
  label,
  description,
  template,
  error,
  children,
  inline,
}: {
  id: string;
  label: string;
  description?: string;
  template?: boolean;
  error?: string;
  children: ReactNode;
  inline?: boolean;
}) {
  return (
    <div
      className={cn("space-y-1.5", inline && "flex items-center justify-between gap-3 space-y-0")}
    >
      <div className="flex items-center gap-1.5">
        <Label htmlFor={id}>{label}</Label>
        {template ? (
          <span
            className="bg-accent text-accent-foreground inline-flex items-center gap-0.5 rounded px-1 text-[10.5px] font-medium"
            title="Accepts {{ expressions }}"
          >
            <Braces className="size-3" aria-hidden />
            template
          </span>
        ) : null}
      </div>
      {children}
      {description && !inline ? <FieldHint>{description}</FieldHint> : null}
      {error ? (
        <p className="text-danger text-xs font-medium" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}

/** A JSON value edited as text: parsed on every change, kept as typed text until it parses. */
function JsonField({
  id,
  value,
  onChange,
  disabled,
  rows = 6,
}: {
  id: string;
  value: unknown;
  onChange: (value: unknown) => void;
  disabled?: boolean;
  rows?: number;
}) {
  // The inspector remounts for every node, so the text only needs its initial value here.
  const [text, setText] = useState(() =>
    value === undefined ? "" : JSON.stringify(value, null, 2),
  );
  const [error, setError] = useState<string | null>(null);

  return (
    <div className="space-y-1">
      <Textarea
        id={id}
        rows={rows}
        className={cn(mono, error && "border-danger")}
        value={text}
        disabled={disabled}
        spellCheck={false}
        onChange={(event) => {
          setText(event.target.value);
          try {
            const parsed: unknown = event.target.value.trim()
              ? JSON.parse(event.target.value)
              : null;
            setError(null);
            onChange(parsed);
          } catch (exc) {
            setError(exc instanceof Error ? exc.message : "Not valid JSON");
          }
        }}
      />
      {error ? <p className="text-danger text-xs">JSON: {error}</p> : null}
    </div>
  );
}

function CronField({
  id,
  value,
  timezone,
  onChange,
  disabled,
}: {
  id: string;
  value: string;
  timezone: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  const preview = useCronPreview();
  const { mutate } = preview;
  useEffect(() => {
    if (!value.trim()) return;
    const timer = setTimeout(() => mutate({ expression: value, timezone, count: 3 }), 350);
    return () => clearTimeout(timer);
  }, [value, timezone, mutate]);
  const result = preview.data;
  return (
    <div className="space-y-1.5">
      <Input
        id={id}
        className={mono}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        placeholder="0 8 * * MON-FRI"
      />
      {result ? (
        result.valid ? (
          <p className="text-muted-foreground text-xs">
            <span className="text-foreground font-medium">{result.description}</span>
            {result.next.length
              ? `; next runs ${result.next.map(formatDateTime).join(", ")}`
              : null}
          </p>
        ) : (
          <p className="text-danger text-xs">{result.error}</p>
        )
      ) : null}
    </div>
  );
}

let zones: string[] | null = null;
function timeZones(): string[] {
  if (!zones) {
    const supported = (Intl as unknown as { supportedValuesOf?: (key: string) => string[] })
      .supportedValuesOf;
    zones = supported ? supported("timeZone") : ["UTC"];
    if (!zones.includes("UTC")) zones = ["UTC", ...zones];
  }
  return zones;
}

type Row = Record<string, unknown>;

function RowList({
  rows,
  onChange,
  disabled,
  empty,
  make,
  render,
  addLabel,
}: {
  rows: Row[];
  onChange: (rows: Row[]) => void;
  disabled?: boolean;
  empty: string;
  make: () => Row;
  render: (row: Row, update: (patch: Row) => void, index: number) => ReactNode;
  addLabel: string;
}) {
  return (
    <div className="space-y-2">
      {rows.length === 0 ? <p className="text-subtle text-xs">{empty}</p> : null}
      {rows.map((row, index) => (
        <div key={index} className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            {render(
              row,
              (patch) => onChange(rows.map((r, i) => (i === index ? { ...r, ...patch } : r))),
              index,
            )}
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            disabled={disabled}
            aria-label="Remove"
            onClick={() => onChange(rows.filter((_, i) => i !== index))}
          >
            <Trash2 />
          </Button>
        </div>
      ))}
      <Button
        type="button"
        variant="secondary"
        size="sm"
        disabled={disabled}
        onClick={() => onChange([...rows, make()])}
      >
        <Plus /> {addLabel}
      </Button>
    </div>
  );
}

function textOf(value: unknown): string {
  if (value === null || value === undefined) return "";
  return typeof value === "string" ? value : JSON.stringify(value);
}

/** Text that holds a JSON literal (true, 42, [..]) is kept as that value, other text as text. */
function looseValue(text: string): unknown {
  const trimmed = text.trim();
  if (/^(true|false|null|-?\d+(\.\d+)?)$/.test(trimmed) || /^[[{]/.test(trimmed)) {
    try {
      return JSON.parse(trimmed);
    } catch {
      return text;
    }
  }
  return text;
}

function operatorsFrom(root: JsonSchema, defName: string): string[] {
  const field = root.$defs?.[defName]?.properties?.operator;
  return (field?.enum as string[] | undefined) ?? ["equals"];
}

const UNARY = new Set(["is_empty", "is_not_empty", "exists", "not_exists", "is_true", "is_false"]);

function Field({
  name,
  schema: raw,
  value,
  onChange,
  ctx,
  required,
  config,
}: {
  name: string;
  schema: JsonSchema;
  value: unknown;
  onChange: (value: unknown) => void;
  ctx: FormContext;
  required: boolean;
  config: Record<string, unknown>;
}) {
  const { schema, nullable } = unwrapNullable(raw, ctx.root);
  const id = `field-${name}`;
  const widget = schema["x-widget"] ?? raw["x-widget"];
  const template = Boolean(schema["x-template"] ?? raw["x-template"]);
  const label = fieldTitle(name, schema) + (required ? "" : "");
  const error = issueFor(ctx.issues, name);
  const description = schema.description ?? raw.description;
  const type = schemaType(schema);
  const disabled = ctx.readOnly;
  const shell = (children: ReactNode, inline = false) => (
    <FieldShell
      id={id}
      label={label}
      description={description}
      template={template}
      error={error}
      inline={inline}
    >
      {children}
    </FieldShell>
  );

  if (widget === "credential") {
    const accepted = schema["x-credential-types"] ?? raw["x-credential-types"] ?? [];
    const options = ctx.credentials.filter((c) => accepted.includes(c.type));
    return shell(
      <div className="space-y-1">
        <NativeSelect
          id={id}
          value={textOf(value)}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value || null)}
        >
          <option value="">{nullable ? "None" : "Choose a credential"}</option>
          {options.map((credential) => (
            <option key={credential.id} value={credential.id}>
              {credential.name}
            </option>
          ))}
        </NativeSelect>
        {options.length === 0 ? (
          <p className="text-muted-foreground text-xs">
            No {accepted.join(" or ")} credential yet.{" "}
            <Link
              href={`/w/${ctx.workspace}/credentials`}
              className="text-primary font-medium hover:underline"
            >
              Add one
            </Link>
          </p>
        ) : null}
      </div>,
    );
  }
  if (widget === "cron") {
    return shell(
      <CronField
        id={id}
        value={textOf(value)}
        timezone={textOf(config.timezone) || "UTC"}
        onChange={onChange}
        disabled={disabled}
      />,
    );
  }
  if (widget === "timezone") {
    return shell(
      <NativeSelect
        id={id}
        value={textOf(value) || "UTC"}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      >
        {timeZones().map((zone) => (
          <option key={zone} value={zone}>
            {zone}
          </option>
        ))}
      </NativeSelect>,
    );
  }
  if (widget === "key-value") {
    return shell(
      <RowList
        rows={(Array.isArray(value) ? value : []) as Row[]}
        onChange={onChange}
        disabled={disabled}
        empty="None."
        addLabel="Add"
        make={() => ({ name: "", value: "" })}
        render={(row, update) => (
          <div className="grid grid-cols-2 gap-2">
            <Input
              aria-label="Name"
              placeholder="Name"
              className={mono}
              value={textOf(row.name)}
              disabled={disabled}
              onChange={(e) => update({ name: e.target.value })}
            />
            <Input
              aria-label="Value"
              placeholder="Value or {{ template }}"
              className={mono}
              value={textOf(row.value)}
              disabled={disabled}
              onChange={(e) => update({ value: e.target.value })}
            />
          </div>
        )}
      />,
    );
  }
  if (widget === "assignments") {
    return shell(
      <RowList
        rows={(Array.isArray(value) ? value : []) as Row[]}
        onChange={onChange}
        disabled={disabled}
        empty="Nothing set yet."
        addLabel="Add variable"
        make={() => ({ name: "", value: "" })}
        render={(row, update) => (
          <div className="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] gap-2">
            <Input
              aria-label="Variable name"
              placeholder="name"
              className={mono}
              value={textOf(row.name)}
              disabled={disabled}
              onChange={(e) => update({ name: e.target.value })}
            />
            <Input
              aria-label="Value"
              placeholder="{{ input.total }}"
              className={mono}
              value={textOf(row.value)}
              disabled={disabled}
              onChange={(e) => update({ value: looseValue(e.target.value) })}
            />
          </div>
        )}
      />,
    );
  }
  if (widget === "conditions" || widget === "cases") {
    const isCases = widget === "cases";
    const operators = operatorsFrom(ctx.root, isCases ? "Case" : "Condition");
    return shell(
      <RowList
        rows={(Array.isArray(value) ? value : []) as Row[]}
        onChange={onChange}
        disabled={disabled}
        empty={isCases ? "Add a case for each output." : "Add a condition."}
        addLabel={isCases ? "Add case" : "Add condition"}
        make={() =>
          isCases
            ? { port: "", operator: "equals", value: "" }
            : { left: "", operator: "equals", right: "" }
        }
        render={(row, update) => (
          <div className="grid grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,1.2fr)] gap-2">
            {isCases ? (
              <Input
                aria-label="Output name"
                placeholder="output"
                className={mono}
                value={textOf(row.port)}
                disabled={disabled}
                onChange={(e) => update({ port: e.target.value })}
              />
            ) : (
              <Input
                aria-label="Value to test"
                placeholder="{{ input.total }}"
                className={mono}
                value={textOf(row.left)}
                disabled={disabled}
                onChange={(e) => update({ left: looseValue(e.target.value) })}
              />
            )}
            <NativeSelect
              aria-label="Operator"
              value={textOf(row.operator) || "equals"}
              disabled={disabled}
              onChange={(e) => update({ operator: e.target.value })}
            >
              {operators.map((operator) => (
                <option key={operator} value={operator}>
                  {operator.replace(/_/g, " ")}
                </option>
              ))}
            </NativeSelect>
            {UNARY.has(textOf(row.operator)) ? (
              <span />
            ) : (
              <Input
                aria-label="Compare with"
                placeholder="500"
                className={mono}
                value={textOf(isCases ? row.value : row.right)}
                disabled={disabled}
                onChange={(e) =>
                  update(
                    isCases
                      ? { value: looseValue(e.target.value) }
                      : { right: looseValue(e.target.value) },
                  )
                }
              />
            )}
          </div>
        )}
      />,
    );
  }
  if (widget === "parameters") {
    return shell(
      <RowList
        rows={((Array.isArray(value) ? value : []) as unknown[]).map((v) => ({ value: v }))}
        onChange={(rows) => onChange(rows.map((r) => r.value))}
        disabled={disabled}
        empty="No parameters: the query uses none of $1, $2, ..."
        addLabel="Add parameter"
        make={() => ({ value: "" })}
        render={(row, update, index) => (
          <Input
            aria-label={`Parameter ${index + 1}`}
            placeholder={`$${index + 1}: {{ input.id }}`}
            className={mono}
            value={textOf(row.value)}
            disabled={disabled}
            onChange={(e) => update({ value: looseValue(e.target.value) })}
          />
        )}
      />,
    );
  }
  if (widget === "json" || type === undefined) {
    return shell(<JsonField id={id} value={value} onChange={onChange} disabled={disabled} />);
  }
  if (schema.enum) {
    return shell(
      <NativeSelect
        id={id}
        value={textOf(value)}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      >
        {schema.enum.map((option) => (
          <option key={String(option)} value={String(option)}>
            {String(option).replace(/_/g, " ")}
          </option>
        ))}
      </NativeSelect>,
    );
  }
  if (type === "boolean") {
    return shell(
      <Switch
        id={id}
        checked={Boolean(value)}
        disabled={disabled}
        onCheckedChange={(checked) => onChange(checked)}
      />,
      true,
    );
  }
  if (type === "integer" || type === "number") {
    return shell(
      <Input
        id={id}
        type="number"
        className="tabular-nums"
        value={value === null || value === undefined ? "" : String(value)}
        min={schema.minimum}
        max={schema.maximum}
        step={type === "integer" ? 1 : "any"}
        disabled={disabled}
        onChange={(e) =>
          onChange(
            e.target.value === ""
              ? nullable
                ? null
                : defaultFor(schema, ctx.root)
              : Number(e.target.value),
          )
        }
      />,
    );
  }
  if (type === "array") {
    const items = resolveRef(schema.items ?? {}, ctx.root);
    const numeric = schemaType(items) === "integer";
    return shell(
      <Input
        id={id}
        className={mono}
        value={Array.isArray(value) ? value.join(", ") : ""}
        disabled={disabled}
        onChange={(e) =>
          onChange(
            e.target.value
              .split(",")
              .map((part) => part.trim())
              .filter(Boolean)
              .map((part) => (numeric ? Number(part) : part)),
          )
        }
      />,
    );
  }
  if (widget === "textarea" || widget === "sql") {
    return shell(
      <Textarea
        id={id}
        rows={widget === "sql" ? 6 : 5}
        className={cn((widget === "sql" || template) && mono)}
        value={textOf(value)}
        disabled={disabled}
        spellCheck={widget !== "sql"}
        onChange={(e) => onChange(e.target.value)}
      />,
    );
  }
  return shell(
    <Input
      id={id}
      className={cn((template || widget === "expression") && mono)}
      value={textOf(value)}
      disabled={disabled}
      placeholder={widget === "expression" ? "input.items[?qty > `0`]" : undefined}
      onChange={(e) => onChange(nullable && e.target.value === "" ? null : e.target.value)}
    />,
  );
}

export function SchemaForm({
  schema,
  value,
  onChange,
  workspace,
  credentials,
  issues,
  readOnly = false,
}: {
  schema: JsonSchema;
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
  workspace: string;
  credentials: Credential[];
  issues: Map<string, string>;
  readOnly?: boolean;
}) {
  const ctx: FormContext = { root: schema, workspace, credentials, issues, readOnly };
  const required = new Set(schema.required ?? []);
  const general = issues.get("");
  return (
    <div className="space-y-4">
      {general ? (
        <p className="bg-danger-soft text-danger rounded-lg px-3 py-2 text-xs" role="alert">
          {general}
        </p>
      ) : null}
      {Object.entries(schema.properties ?? {}).map(([name, field]) => (
        <Field
          key={name}
          name={name}
          schema={field}
          value={value[name]}
          required={required.has(name)}
          config={value}
          ctx={ctx}
          onChange={(next) => onChange({ ...value, [name]: next })}
        />
      ))}
    </div>
  );
}
