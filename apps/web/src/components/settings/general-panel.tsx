"use client";

import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { FieldHint, Input, Label, NativeSelect, Textarea } from "@/components/ui/input";
import { useUpdateWorkspace } from "@/lib/queries";
import { timeZoneOptions } from "@/lib/timezones";
import type { Workspace } from "@/lib/types";

export function GeneralPanel({ workspace, editable }: { workspace: Workspace; editable: boolean }) {
  const update = useUpdateWorkspace(workspace.slug);
  const [name, setName] = useState(workspace.name);
  const [description, setDescription] = useState(workspace.description);
  const [timezone, setTimezone] = useState(workspace.settings.timezone);
  const [retention, setRetention] = useState(String(workspace.settings.retention_days));
  const [timeout, setTimeoutValue] = useState(String(workspace.settings.default_timeout_s));

  async function submit(event: FormEvent) {
    event.preventDefault();
    try {
      await update.mutateAsync({
        name,
        description,
        settings: {
          timezone,
          retention_days: Number(retention),
          default_timeout_s: Number(timeout),
        },
      });
      toast.success("Workspace updated");
    } catch (error) {
      toast.error((error as Error).message);
    }
  }

  return (
    <Card>
      <CardContent>
        <form onSubmit={submit} className="max-w-xl space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="settings-name">Name</Label>
            <Input
              id="settings-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={!editable}
              required
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="settings-description">Description</Label>
            <Textarea
              id="settings-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              disabled={!editable}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="settings-timezone">Time zone</Label>
            <NativeSelect
              id="settings-timezone"
              value={timezone}
              onChange={(e) => setTimezone(e.target.value)}
              disabled={!editable}
            >
              {timeZoneOptions(timezone).map((zone) => (
                <option key={zone} value={zone}>
                  {zone}
                </option>
              ))}
            </NativeSelect>
            <FieldHint>
              The dashboard buckets runs by this zone; new schedules start in it.
            </FieldHint>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="settings-retention">Keep executions for (days)</Label>
              <Input
                id="settings-retention"
                type="number"
                min={1}
                max={3650}
                value={retention}
                onChange={(e) => setRetention(e.target.value)}
                disabled={!editable}
                required
              />
              <FieldHint>Older finished runs, their steps and logs are pruned.</FieldHint>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="settings-timeout">Default timeout (seconds)</Label>
              <Input
                id="settings-timeout"
                type="number"
                min={10}
                max={604800}
                value={timeout}
                onChange={(e) => setTimeoutValue(e.target.value)}
                disabled={!editable}
                required
              />
              <FieldHint>For new workflows; each workflow can change it.</FieldHint>
            </div>
          </div>
          <div className="space-y-1.5">
            <Label>Address</Label>
            <FieldHint>
              This workspace lives at <code className="font-mono">/w/{workspace.slug}</code>.
              Webhooks are served under <code className="font-mono">/hooks/{workspace.slug}/</code>{" "}
              and API calls accept the slug or the id{" "}
              <code className="font-mono">{workspace.id}</code>.
            </FieldHint>
          </div>
          {editable ? (
            <Button type="submit" disabled={update.isPending || !name.trim()}>
              Save changes
            </Button>
          ) : (
            <FieldHint>Only owners can change workspace settings.</FieldHint>
          )}
        </form>
      </CardContent>
    </Card>
  );
}
