"use client";

import { KeyRound } from "lucide-react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { CopyField } from "@/components/settings/copy-field";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { EmptyState, ErrorNotice, Skeleton } from "@/components/ui/feedback";
import { FieldHint, Input, Label, NativeSelect } from "@/components/ui/input";
import { formatDate, formatRelative } from "@/lib/format";
import { runtimeEnv } from "@/lib/runtime-env";
import { useApiKeyActions, useApiKeys } from "@/lib/queries";
import type { ApiKeyCreated } from "@/lib/types";

export function ApiKeysPanel({ workspace }: { workspace: string }) {
  const keys = useApiKeys(workspace);
  const actions = useApiKeyActions(workspace);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [role, setRole] = useState<"viewer" | "editor">("viewer");
  const [expires, setExpires] = useState("90");
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);

  async function create(event: FormEvent) {
    event.preventDefault();
    const key = await actions.create.mutateAsync({
      name,
      role,
      expires_in_days: expires ? Number(expires) : null,
    });
    setCreated(key);
    setName("");
  }

  const curl = created
    ? `curl -s ${runtimeEnv().apiUrl}/api/v1/workspaces/${workspace}/executions?status=failed -H "authorization: Bearer ${created.key}"`
    : "";

  return (
    <Card>
      <div className="border-border flex items-center justify-between gap-3 border-b px-5 py-3.5">
        <p className="text-muted-foreground text-[13px]">
          Keys let scripts and services run workflows, publish events and read executions.
        </p>
        <Button size="sm" onClick={() => setOpen(true)}>
          <KeyRound /> Create key
        </Button>
      </div>
      {keys.isLoading ? (
        <div className="p-5">
          <Skeleton className="h-10" />
        </div>
      ) : keys.data?.length ? (
        <ul className="divide-border divide-y">
          {keys.data.map((key) => (
            <li key={key.id} className="flex flex-wrap items-center gap-3 px-5 py-3">
              <div className="min-w-0 flex-1">
                <p className="flex items-center gap-2 text-[13.5px] font-medium">
                  {key.name}
                  <Badge tone="outline" className="capitalize">
                    {key.role}
                  </Badge>
                  {key.revoked_at ? <Badge tone="danger">Revoked</Badge> : null}
                </p>
                <p className="text-muted-foreground text-xs">
                  <code className="font-mono">wfk_{key.prefix}_...</code> &middot; created{" "}
                  {formatRelative(key.created_at)} &middot;{" "}
                  {key.last_used_at
                    ? `last used ${formatRelative(key.last_used_at)}`
                    : "never used"}
                  {key.expires_at ? <> &middot; expires {formatDate(key.expires_at)}</> : null}
                </p>
              </div>
              {!key.revoked_at ? (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={async () => {
                    await actions.revoke.mutateAsync(key.id);
                    toast.success(`${key.name} revoked`);
                  }}
                >
                  Revoke
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState
          icon={<KeyRound />}
          title="No API keys yet"
          description="Create one to call WorkflowEngine from CI jobs, scripts and other services."
        />
      )}
      <Dialog
        open={open}
        onOpenChange={(next) => {
          setOpen(next);
          if (!next) setCreated(null);
        }}
      >
        <DialogContent
          title={created ? "Copy your key now" : "Create an API key"}
          description={
            created
              ? "This is the only time the full key is shown. Only a keyed hash is stored."
              : "Keys are scoped to this workspace."
          }
          className="w-[min(92vw,36rem)]"
        >
          {created ? (
            <div className="space-y-3">
              <CopyField value={created.key} label="API key" />
              <Label>Try it</Label>
              <CopyField value={curl} label="Example request" />
              <DialogFooter>
                <Button
                  onClick={() => {
                    setOpen(false);
                    setCreated(null);
                  }}
                >
                  Done
                </Button>
              </DialogFooter>
            </div>
          ) : (
            <form onSubmit={create} className="space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="key-name">Name</Label>
                <Input
                  id="key-name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Nightly billing job"
                  required
                  autoFocus
                />
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="key-role">Access</Label>
                  <NativeSelect
                    id="key-role"
                    value={role}
                    onChange={(e) => setRole(e.target.value as "viewer" | "editor")}
                  >
                    <option value="viewer">Viewer: read workflows and runs</option>
                    <option value="editor">Editor: also run and publish events</option>
                  </NativeSelect>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="key-expiry">Expires</Label>
                  <NativeSelect
                    id="key-expiry"
                    value={expires}
                    onChange={(e) => setExpires(e.target.value)}
                  >
                    <option value="30">In 30 days</option>
                    <option value="90">In 90 days</option>
                    <option value="365">In a year</option>
                    <option value="">Never</option>
                  </NativeSelect>
                </div>
              </div>
              <FieldHint>
                Use it as <code className="font-mono">Authorization: Bearer wfk_...</code>. Webhook
                triggers do not need a key.
              </FieldHint>
              {actions.create.error ? <ErrorNotice message={actions.create.error.message} /> : null}
              <DialogFooter>
                <Button type="button" variant="secondary" onClick={() => setOpen(false)}>
                  Cancel
                </Button>
                <Button type="submit" disabled={!name.trim() || actions.create.isPending}>
                  Create key
                </Button>
              </DialogFooter>
            </form>
          )}
        </DialogContent>
      </Dialog>
    </Card>
  );
}
