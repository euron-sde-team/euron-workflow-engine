"use client";

import { Pencil, Plus, Trash2, Variable as VariableIcon } from "lucide-react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { EmptyState, ErrorNotice, Skeleton } from "@/components/ui/feedback";
import { FieldHint, Input, Label, Textarea } from "@/components/ui/input";
import { formatRelative } from "@/lib/format";
import { useVariableActions, useVariables } from "@/lib/queries";
import type { Variable } from "@/lib/types";

const KEY = /^[A-Z][A-Z0-9_]{0,63}$/;

function VariableForm({
  existing,
  workspace,
  onDone,
}: {
  existing: Variable | null;
  workspace: string;
  onDone: () => void;
}) {
  const { put } = useVariableActions(workspace);
  const [key, setKey] = useState(existing?.key ?? "");
  const [value, setValue] = useState(existing?.value ?? "");
  const [description, setDescription] = useState(existing?.description ?? "");
  const validKey = KEY.test(key);

  function submit(event: FormEvent) {
    event.preventDefault();
    put.mutate(
      { key, value, description },
      {
        onSuccess: () => {
          toast.success(`Saved ${key}`);
          onDone();
        },
      },
    );
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="space-y-1.5">
        <Label htmlFor="variable-key">Key</Label>
        <Input
          id="variable-key"
          value={key}
          onChange={(e) => setKey(e.target.value.toUpperCase())}
          className="font-mono"
          placeholder="FULFILLMENT_API"
          disabled={Boolean(existing)}
          required
          autoFocus={!existing}
        />
        <FieldHint>
          Read it in any template as{" "}
          <code className="font-mono">{`{{ env.${key || "KEY"} }}`}</code>. Upper case letters,
          digits and underscores.
        </FieldHint>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="variable-value">Value</Label>
        <Textarea
          id="variable-value"
          rows={3}
          className="font-mono text-[12.5px]"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          autoFocus={Boolean(existing)}
        />
        <FieldHint>Variables are plain text. Put secrets in credentials instead.</FieldHint>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="variable-description">Description</Label>
        <Input
          id="variable-description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>
      {put.error ? <ErrorNotice message={put.error.message} /> : null}
      <DialogFooter>
        <Button type="button" variant="secondary" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" disabled={!validKey || put.isPending} data-testid="save-variable">
          Save
        </Button>
      </DialogFooter>
    </form>
  );
}

export function VariablesPanel({ workspace, editable }: { workspace: string; editable: boolean }) {
  const variables = useVariables(workspace);
  const { remove } = useVariableActions(workspace);
  const [editing, setEditing] = useState<Variable | "new" | null>(null);

  return (
    <Card>
      <div className="border-border flex items-center justify-between gap-3 border-b px-5 py-3.5">
        <p className="text-muted-foreground text-[13px]">
          Shared settings such as API base URLs, read by every workflow in this workspace.
        </p>
        {editable ? (
          <Button size="sm" onClick={() => setEditing("new")} data-testid="new-variable">
            <Plus /> Add variable
          </Button>
        ) : null}
      </div>
      {variables.isLoading ? (
        <div className="p-5">
          <Skeleton className="h-10" />
        </div>
      ) : variables.data?.length ? (
        <ul className="divide-border divide-y">
          {variables.data.map((variable) => (
            <li key={variable.key} className="flex flex-wrap items-center gap-3 px-5 py-3">
              <div className="min-w-0 flex-1">
                <p className="font-mono text-[13px] font-medium">{variable.key}</p>
                <p className="text-muted-foreground truncate font-mono text-[12px]">
                  {variable.value || "(empty)"}
                </p>
                {variable.description ? (
                  <p className="text-subtle mt-0.5 text-[12px]">{variable.description}</p>
                ) : null}
              </div>
              <span className="text-subtle hidden text-[12px] sm:block">
                updated {formatRelative(variable.updated_at)}
              </span>
              {editable ? (
                <span className="flex gap-1">
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    aria-label={`Edit ${variable.key}`}
                    onClick={() => setEditing(variable)}
                  >
                    <Pencil />
                  </Button>
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    aria-label={`Delete ${variable.key}`}
                    onClick={() =>
                      remove.mutate(variable.key, {
                        onSuccess: () => toast.success(`Deleted ${variable.key}`),
                        onError: (error) => toast.error(error.message),
                      })
                    }
                  >
                    <Trash2 />
                  </Button>
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState
          icon={<VariableIcon />}
          title="No variables yet"
          description="Templates expect some, for example the base URL of an API."
        />
      )}
      <Dialog open={editing !== null} onOpenChange={(open) => !open && setEditing(null)}>
        {editing !== null ? (
          <DialogContent title={editing === "new" ? "Add a variable" : `Edit ${editing.key}`}>
            <VariableForm
              existing={editing === "new" ? null : editing}
              workspace={workspace}
              onDone={() => setEditing(null)}
            />
          </DialogContent>
        ) : null}
      </Dialog>
    </Card>
  );
}
