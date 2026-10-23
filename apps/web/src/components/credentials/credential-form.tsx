"use client";

import { LockKeyhole } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { DialogFooter } from "@/components/ui/dialog";
import { ErrorNotice, Spinner } from "@/components/ui/feedback";
import { FieldHint, Input, Label, NativeSelect, Textarea } from "@/components/ui/input";
import { fieldTitle, resolveRef, schemaType } from "@/lib/schema";
import type { Credential, CredentialType, JsonSchema } from "@/lib/types";

export type CredentialSubmit = {
  name: string;
  description: string;
  data: Record<string, unknown>;
};

/** The starting values: public fields from the stored credential, secrets always blank. */
export function initialValues(type: CredentialType, existing?: Credential): Record<string, string> {
  const values: Record<string, string> = {};
  for (const [name, field] of Object.entries(type.json_schema.properties ?? {})) {
    const stored = existing?.public_fields[name];
    const fallback = field.default;
    values[name] = field["x-secret"] ? "" : String(stored ?? fallback ?? "");
  }
  return values;
}

/** Turns form strings into the JSON the API validates; blank secrets are left out on edit. */
export function toPayload(
  type: CredentialType,
  values: Record<string, string>,
  editing: boolean,
): Record<string, unknown> {
  const data: Record<string, unknown> = {};
  for (const [name, raw] of Object.entries(type.json_schema.properties ?? {})) {
    const field = resolveRef(raw, type.json_schema);
    const value = values[name] ?? "";
    if (field["x-secret"] && editing && value === "") continue;
    data[name] = schemaType(field) === "integer" && value !== "" ? Number(value) : value;
  }
  return data;
}

export function CredentialForm({
  type,
  existing,
  pending,
  error,
  onCancel,
  onSubmit,
}: {
  type: CredentialType;
  existing?: Credential;
  pending: boolean;
  error: string | null;
  onCancel: () => void;
  onSubmit: (body: CredentialSubmit) => void;
}) {
  const editing = Boolean(existing);
  const [name, setName] = useState(existing?.name ?? "");
  const [description, setDescription] = useState(existing?.description ?? "");
  const [values, setValues] = useState(() => initialValues(type, existing));
  const required = new Set(type.json_schema.required ?? []);

  function submit(event: FormEvent) {
    event.preventDefault();
    onSubmit({ name, description, data: toPayload(type, values, editing) });
  }

  return (
    <form onSubmit={submit} className="space-y-4" autoComplete="off">
      <div className="space-y-1.5">
        <Label htmlFor="credential-name">Name</Label>
        <Input
          id="credential-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={`${type.name} for production`}
          required
          autoFocus
        />
        <FieldHint>Exported workflows refer to credentials by this name.</FieldHint>
      </div>
      {Object.entries(type.json_schema.properties ?? {}).map(([field, raw]) => {
        const schema: JsonSchema = resolveRef(raw, type.json_schema);
        const id = `credential-${field}`;
        const secret = Boolean(schema["x-secret"]);
        const value = values[field] ?? "";
        const set = (next: string) => setValues((current) => ({ ...current, [field]: next }));
        return (
          <div key={field} className="space-y-1.5">
            <Label htmlFor={id} className="flex items-center gap-1.5">
              {fieldTitle(field, schema)}
              {secret ? <LockKeyhole className="text-subtle size-3.5" aria-label="Secret" /> : null}
            </Label>
            {schema.enum ? (
              <NativeSelect id={id} value={value} onChange={(e) => set(e.target.value)}>
                {schema.enum.map((option) => (
                  <option key={String(option)} value={String(option)}>
                    {String(option)}
                  </option>
                ))}
              </NativeSelect>
            ) : (
              <Input
                id={id}
                type={secret ? "password" : schemaType(schema) === "integer" ? "number" : "text"}
                value={value}
                onChange={(e) => set(e.target.value)}
                required={required.has(field) && !(secret && editing)}
                placeholder={secret && editing ? "Unchanged, stored encrypted" : undefined}
                autoComplete={secret ? "new-password" : "off"}
                className={secret ? "font-mono" : undefined}
              />
            )}
            {schema.description ? <FieldHint>{schema.description}</FieldHint> : null}
          </div>
        );
      })}
      <div className="space-y-1.5">
        <Label htmlFor="credential-description">Notes</Label>
        <Textarea
          id="credential-description"
          rows={2}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Who owns it, when it rotates"
        />
      </div>
      <p className="bg-muted text-muted-foreground flex items-start gap-2 rounded-lg px-3 py-2 text-[12px]">
        <LockKeyhole className="mt-0.5 size-3.5 shrink-0" aria-hidden />
        Secret fields are encrypted with a per-credential data key and are never sent back to the
        browser. Leave them blank when editing to keep the stored value.
      </p>
      {error ? <ErrorNotice message={error} /> : null}
      <DialogFooter>
        <Button type="button" variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={pending || !name.trim()} data-testid="save-credential">
          {pending ? <Spinner className="text-primary-foreground" /> : null}
          {editing ? "Save" : "Create credential"}
        </Button>
      </DialogFooter>
    </form>
  );
}
