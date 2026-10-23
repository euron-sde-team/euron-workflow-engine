"use client";

import { History, RotateCcw, Rocket } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { ErrorNotice, Spinner } from "@/components/ui/feedback";
import { FieldHint, Input, Label, NativeSelect, Textarea } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { formatRelative } from "@/lib/format";
import { useVersions } from "@/lib/queries";
import type { Issue, NodeSpec, Workflow } from "@/lib/types";

/*
 * Each dialog keeps its form state in an inner component rendered inside DialogContent.
 * Radix unmounts the content when the dialog closes, so every opening starts from fresh
 * values without resetting state in an effect.
 */

function PublishForm({
  workflow,
  pending,
  error,
  onCancel,
  onPublish,
}: {
  workflow: Workflow;
  pending: boolean;
  error: string | null;
  onCancel: () => void;
  onPublish: (note: string, activate: boolean) => void;
}) {
  const [note, setNote] = useState("");
  const [activate, setActivate] = useState(workflow.active || workflow.published_version === null);
  return (
    <form
      className="space-y-4"
      onSubmit={(event: FormEvent) => {
        event.preventDefault();
        onPublish(note, activate);
      }}
    >
      <div className="space-y-1.5">
        <Label htmlFor="publish-note">What changed</Label>
        <Input
          id="publish-note"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Retry the fulfillment API for longer"
          autoFocus
        />
      </div>
      <label className="border-border flex items-center justify-between gap-3 rounded-lg border p-3 text-[13px]">
        <span>
          <span className="block font-medium">Active</span>
          <span className="text-muted-foreground block text-xs">
            Webhooks, schedules and events start this version.
          </span>
        </span>
        <Switch
          checked={activate}
          onCheckedChange={setActivate}
          aria-label="Activate after publishing"
        />
      </label>
      {error ? <ErrorNotice message={error} /> : null}
      <DialogFooter>
        <Button type="button" variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={pending} data-testid="confirm-publish">
          {pending ? <Spinner className="text-primary-foreground" /> : <Rocket />}
          Publish
        </Button>
      </DialogFooter>
    </form>
  );
}

export function PublishDialog({
  open,
  onOpenChange,
  workflow,
  errors,
  pending,
  error,
  onPublish,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workflow: Workflow;
  errors: Issue[];
  pending: boolean;
  error: string | null;
  onPublish: (note: string, activate: boolean) => void;
}) {
  const next = (workflow.published_version ?? 0) + 1;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title={`Publish version ${next}`}
        description="Published versions are immutable. Active workflows switch to the new version at once."
      >
        {errors.length ? (
          <div className="space-y-2">
            <ErrorNotice
              message={`Fix ${errors.length} problem${errors.length === 1 ? "" : "s"} first.`}
            />
            <ul className="text-danger max-h-40 space-y-1 overflow-y-auto text-xs">
              {errors.slice(0, 8).map((issue, index) => (
                <li key={index}>{issue.message}</li>
              ))}
            </ul>
          </div>
        ) : (
          <PublishForm
            workflow={workflow}
            pending={pending}
            error={error}
            onCancel={() => onOpenChange(false)}
            onPublish={onPublish}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

function initialTrigger(triggers: NodeSpec[]): NodeSpec | undefined {
  return triggers.find((t) => t.type === "trigger.manual") ?? triggers[0];
}

function RunForm({
  triggers,
  pending,
  error,
  onCancel,
  onRun,
}: {
  triggers: NodeSpec[];
  pending: boolean;
  error: string | null;
  onCancel: () => void;
  onRun: (triggerId: string, payload: unknown) => void;
}) {
  const [trigger, setTrigger] = useState(() => initialTrigger(triggers)?.id ?? "");
  const [payload, setPayload] = useState(() =>
    JSON.stringify(initialTrigger(triggers)?.config.sample_payload ?? {}, null, 2),
  );
  const [parseError, setParseError] = useState<string | null>(null);
  return (
    <form
      className="space-y-4"
      onSubmit={(event: FormEvent) => {
        event.preventDefault();
        try {
          const parsed: unknown = payload.trim() ? JSON.parse(payload) : null;
          setParseError(null);
          onRun(trigger, parsed);
        } catch (exc) {
          setParseError(exc instanceof Error ? exc.message : "Not valid JSON");
        }
      }}
    >
      {triggers.length > 1 ? (
        <div className="space-y-1.5">
          <Label htmlFor="run-trigger">Start from</Label>
          <NativeSelect
            id="run-trigger"
            value={trigger}
            onChange={(e) => {
              setTrigger(e.target.value);
              const node = triggers.find((t) => t.id === e.target.value);
              setPayload(JSON.stringify(node?.config.sample_payload ?? {}, null, 2));
            }}
          >
            {triggers.map((node) => (
              <option key={node.id} value={node.id}>
                {node.name}
              </option>
            ))}
          </NativeSelect>
        </div>
      ) : null}
      <div className="space-y-1.5">
        <Label htmlFor="run-payload">Trigger payload</Label>
        <Textarea
          id="run-payload"
          rows={8}
          className="font-mono text-[12px]"
          value={payload}
          onChange={(e) => setPayload(e.target.value)}
          spellCheck={false}
        />
        <FieldHint>Read in templates as trigger, for example {"{{ trigger.order_id }}"}.</FieldHint>
        {parseError ? <p className="text-danger text-xs">JSON: {parseError}</p> : null}
      </div>
      {error ? <ErrorNotice message={error} /> : null}
      <DialogFooter>
        <Button type="button" variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={pending || !trigger} data-testid="confirm-run">
          {pending ? <Spinner className="text-primary-foreground" /> : null}
          Run
        </Button>
      </DialogFooter>
    </form>
  );
}

export function RunDialog({
  open,
  onOpenChange,
  triggers,
  pending,
  error,
  onRun,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  triggers: NodeSpec[];
  pending: boolean;
  error: string | null;
  onRun: (triggerId: string, payload: unknown) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title="Run the draft"
        description="A test run uses the saved draft and is marked as a test in the history."
      >
        <RunForm
          triggers={triggers}
          pending={pending}
          error={error}
          onCancel={() => onOpenChange(false)}
          onRun={onRun}
        />
      </DialogContent>
    </Dialog>
  );
}

type SettingsBody = {
  name: string;
  description: string;
  tags: string[];
  concurrency_limit?: number;
  clear_concurrency_limit: boolean;
  timeout_s: number;
};

function SettingsForm({
  workflow,
  pending,
  error,
  onCancel,
  onSave,
}: {
  workflow: Workflow;
  pending: boolean;
  error: string | null;
  onCancel: () => void;
  onSave: (body: SettingsBody) => void;
}) {
  const [name, setName] = useState(workflow.name);
  const [description, setDescription] = useState(workflow.description);
  const [tags, setTags] = useState(workflow.tags.join(", "));
  const [limit, setLimit] = useState(
    workflow.concurrency_limit ? String(workflow.concurrency_limit) : "",
  );
  const [timeout, setTimeoutValue] = useState(String(workflow.timeout_s));
  return (
    <form
      className="space-y-4"
      onSubmit={(event: FormEvent) => {
        event.preventDefault();
        onSave({
          name,
          description,
          tags: tags
            .split(",")
            .map((t) => t.trim())
            .filter(Boolean),
          concurrency_limit: limit ? Number(limit) : undefined,
          clear_concurrency_limit: !limit,
          timeout_s: Number(timeout) || 3600,
        });
      }}
    >
      <div className="space-y-1.5">
        <Label htmlFor="wf-name">Name</Label>
        <Input id="wf-name" value={name} onChange={(e) => setName(e.target.value)} required />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="wf-description">Description</Label>
        <Textarea
          id="wf-description"
          rows={3}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="wf-tags">Tags</Label>
        <Input
          id="wf-tags"
          value={tags}
          onChange={(e) => setTags(e.target.value)}
          placeholder="billing, nightly"
        />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1.5">
          <Label htmlFor="wf-limit">Concurrency limit</Label>
          <Input
            id="wf-limit"
            type="number"
            min={1}
            max={1000}
            value={limit}
            onChange={(e) => setLimit(e.target.value)}
            placeholder="Unlimited"
          />
          <FieldHint>Extra runs wait in the queue.</FieldHint>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="wf-timeout">Timeout (seconds)</Label>
          <Input
            id="wf-timeout"
            type="number"
            min={10}
            max={604800}
            value={timeout}
            onChange={(e) => setTimeoutValue(e.target.value)}
          />
          <FieldHint>For the whole execution.</FieldHint>
        </div>
      </div>
      {error ? <ErrorNotice message={error} /> : null}
      <DialogFooter>
        <Button type="button" variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={pending || !name.trim()}>
          Save
        </Button>
      </DialogFooter>
    </form>
  );
}

export function SettingsDialog({
  open,
  onOpenChange,
  workflow,
  pending,
  error,
  onSave,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workflow: Workflow;
  pending: boolean;
  error: string | null;
  onSave: (body: SettingsBody) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title="Workflow settings">
        <SettingsForm
          workflow={workflow}
          pending={pending}
          error={error}
          onCancel={() => onOpenChange(false)}
          onSave={onSave}
        />
      </DialogContent>
    </Dialog>
  );
}

export function VersionsDialog({
  open,
  onOpenChange,
  workspace,
  workflowId,
  readOnly,
  pending,
  onRestore,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workspace: string;
  workflowId: string;
  readOnly: boolean;
  pending: boolean;
  onRestore: (number: number) => void;
}) {
  const versions = useVersions(workspace, workflowId, open);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title="Versions"
        description="Every published version, newest first. Restoring copies it into the draft."
      >
        {versions.isLoading ? <Spinner /> : null}
        {versions.data?.length === 0 ? (
          <p className="text-muted-foreground text-[13px]">Nothing published yet.</p>
        ) : (
          <ul className="divide-border max-h-80 divide-y overflow-y-auto">
            {versions.data?.map((version) => (
              <li key={version.id} className="flex items-center gap-3 py-2.5">
                <History className="text-muted-foreground size-4" aria-hidden />
                <div className="min-w-0 flex-1">
                  <p className="text-[13px] font-medium">
                    Version {version.number}{" "}
                    {version.is_current ? <Badge tone="primary">current</Badge> : null}
                  </p>
                  <p className="text-muted-foreground truncate text-xs">
                    {version.note || "No note"} &middot; {version.node_count} nodes &middot;{" "}
                    {formatRelative(version.created_at)}
                  </p>
                </div>
                {!readOnly ? (
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={pending}
                    onClick={() => onRestore(version.number)}
                  >
                    <RotateCcw /> Restore
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </DialogContent>
    </Dialog>
  );
}
