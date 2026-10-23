"use client";

import { KeyRound, MoreHorizontal, Pencil, Plus, ShieldCheck, Trash2 } from "lucide-react";
import { useParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { CredentialForm, type CredentialSubmit } from "@/components/credentials/credential-form";
import { NodeIcon } from "@/components/node-icon";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { EmptyState, ErrorNotice, Skeleton } from "@/components/ui/feedback";
import { PageBody, PageHeader } from "@/components/ui/page";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatRelative } from "@/lib/format";
import {
  canEdit,
  useCredentialActions,
  useCredentials,
  useCredentialTypes,
  useCurrentWorkspace,
} from "@/lib/queries";
import type { Credential, CredentialType } from "@/lib/types";

type Editing =
  { mode: "create"; type: CredentialType | null } | { mode: "edit"; credential: Credential };

function TypePicker({
  types,
  onPick,
}: {
  types: CredentialType[];
  onPick: (type: CredentialType) => void;
}) {
  return (
    <ul className="grid gap-2 sm:grid-cols-2">
      {types.map((type) => (
        <li key={type.type}>
          <button
            type="button"
            onClick={() => onPick(type)}
            className="border-border hover:border-primary hover:bg-accent/40 flex h-full w-full items-start gap-3 rounded-xl border p-3 text-left transition-colors"
            data-testid={`credential-type-${type.type}`}
          >
            <NodeIcon icon={type.icon} category="integration" />
            <span className="min-w-0">
              <span className="block text-[13px] font-semibold">{type.name}</span>
              <span className="text-muted-foreground block text-[12px] leading-snug">
                {type.description}
              </span>
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

function DeleteDialog({
  credential,
  onClose,
  workspace,
}: {
  credential: Credential | null;
  onClose: () => void;
  workspace: string;
}) {
  const { remove } = useCredentialActions(workspace);
  const error = remove.error instanceof ApiError ? remove.error : null;
  const blockers =
    error?.code === "credential_in_use"
      ? ((error.details as { workflows?: string[] } | undefined)?.workflows ?? [])
      : [];
  return (
    <Dialog
      open={Boolean(credential)}
      onOpenChange={(open) => {
        if (!open) {
          remove.reset();
          onClose();
        }
      }}
    >
      {credential ? (
        <DialogContent
          title={`Delete ${credential.name}?`}
          description="The encrypted value is destroyed. Workflows that use it must be changed first."
        >
          {error ? (
            <div className="space-y-2">
              <ErrorNotice message={error.message} />
              {blockers.length ? (
                <ul className="text-muted-foreground list-disc pl-5 text-[13px]">
                  {blockers.map((name) => (
                    <li key={name}>{name}</li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}
          <DialogFooter>
            <Button variant="secondary" onClick={onClose}>
              Keep it
            </Button>
            <Button
              variant="danger"
              disabled={remove.isPending || blockers.length > 0}
              onClick={() =>
                remove.mutate(credential.id, {
                  onSuccess: () => {
                    toast.success(`Deleted ${credential.name}`);
                    onClose();
                  },
                })
              }
              data-testid="confirm-delete-credential"
            >
              <Trash2 /> Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      ) : null}
    </Dialog>
  );
}

export default function CredentialsPage() {
  const { workspace } = useParams<{ workspace: string }>();
  const current = useCurrentWorkspace(workspace);
  const editable = canEdit(current?.role);
  const credentials = useCredentials(workspace);
  const types = useCredentialTypes();
  const actions = useCredentialActions(workspace);
  const [editing, setEditing] = useState<Editing | null>(null);
  const [deleting, setDeleting] = useState<Credential | null>(null);
  const typeMap = new Map((types.data ?? []).map((t) => [t.type, t]));

  const formType =
    editing?.mode === "edit" ? typeMap.get(editing.credential.type) : (editing?.type ?? undefined);
  const mutation = editing?.mode === "edit" ? actions.update : actions.create;

  function close() {
    actions.create.reset();
    actions.update.reset();
    setEditing(null);
  }

  function submit(body: CredentialSubmit) {
    if (!editing) return;
    if (editing.mode === "edit") {
      actions.update.mutate(
        { id: editing.credential.id, ...body },
        {
          onSuccess: (saved) => {
            toast.success(`Saved ${saved.name}`);
            close();
          },
        },
      );
    } else if (editing.type) {
      actions.create.mutate(
        { ...body, type: editing.type.type },
        {
          onSuccess: (saved) => {
            toast.success(`Created ${saved.name}`);
            close();
          },
        },
      );
    }
  }

  return (
    <PageBody>
      <PageHeader
        title="Credentials"
        description="Secrets for HTTP APIs, databases, Slack and webhook signatures. Encrypted at rest and never returned by the API."
        actions={
          editable ? (
            <Button
              onClick={() => setEditing({ mode: "create", type: null })}
              data-testid="new-credential"
            >
              <Plus /> New credential
            </Button>
          ) : null
        }
      />
      {credentials.error ? <ErrorNotice message={credentials.error.message} /> : null}
      {!credentials.data ? (
        <Skeleton className="h-72" />
      ) : credentials.data.length === 0 ? (
        <Card>
          <EmptyState
            icon={<KeyRound />}
            title="No credentials yet"
            description="Add one before configuring nodes that call authenticated APIs."
          />
        </Card>
      ) : (
        <Card className="divide-border divide-y">
          {credentials.data.map((credential) => {
            const type = typeMap.get(credential.type);
            return (
              <div
                key={credential.id}
                className="flex items-center gap-4 px-5 py-3.5"
                data-testid="credential-row"
              >
                <NodeIcon icon={type?.icon ?? "key-round"} category="integration" />
                <div className="min-w-0 flex-1">
                  <p className="flex flex-wrap items-center gap-2 text-[13.5px] font-medium">
                    {credential.name}
                    <Badge tone="outline">{type?.name ?? credential.type}</Badge>
                  </p>
                  <p className="text-muted-foreground mt-0.5 truncate text-[12.5px]">
                    {credential.used_by.length
                      ? `Used by ${credential.used_by.join(", ")}`
                      : "Not used by any workflow"}
                    {credential.description ? <> &middot; {credential.description}</> : null}
                  </p>
                </div>
                <div className="hidden text-right text-[12px] sm:block">
                  <p className="text-muted-foreground flex items-center justify-end gap-1">
                    <ShieldCheck className="text-success size-3.5" aria-hidden />
                    {credential.key_provider === "kms" ? "KMS envelope" : "Local key"}, v
                    {credential.version}
                  </p>
                  <p className="text-subtle mt-0.5">
                    {credential.last_used_at
                      ? `Used ${formatRelative(credential.last_used_at)}`
                      : "Never used"}
                  </p>
                </div>
                {editable ? (
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label={`Actions for ${credential.name}`}
                      >
                        <MoreHorizontal />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem onSelect={() => setEditing({ mode: "edit", credential })}>
                        <Pencil /> Edit or rotate
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        onSelect={() => setDeleting(credential)}
                        className="text-danger"
                      >
                        <Trash2 /> Delete
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                ) : null}
              </div>
            );
          })}
        </Card>
      )}

      <Dialog open={Boolean(editing)} onOpenChange={(open) => !open && close()}>
        {editing ? (
          <DialogContent
            title={
              editing.mode === "edit"
                ? `Edit ${editing.credential.name}`
                : formType
                  ? `New ${formType.name.toLowerCase()} credential`
                  : "New credential"
            }
            description={formType ? formType.description : "Choose what kind of secret to store."}
            className={cn(!formType && "w-[min(94vw,40rem)]")}
          >
            {formType ? (
              <CredentialForm
                type={formType}
                existing={editing.mode === "edit" ? editing.credential : undefined}
                pending={mutation.isPending}
                error={mutation.error?.message ?? null}
                onCancel={close}
                onSubmit={submit}
              />
            ) : (
              <TypePicker
                types={types.data ?? []}
                onPick={(type) => setEditing({ mode: "create", type })}
              />
            )}
          </DialogContent>
        ) : null}
      </Dialog>
      <DeleteDialog credential={deleting} onClose={() => setDeleting(null)} workspace={workspace} />
    </PageBody>
  );
}
