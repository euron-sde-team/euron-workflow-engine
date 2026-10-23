"use client";

import { History } from "lucide-react";
import Link from "next/link";

import { Card } from "@/components/ui/card";
import { EmptyState, ErrorNotice, Skeleton } from "@/components/ui/feedback";
import { formatDateTime, formatRelative } from "@/lib/format";
import { useAudit } from "@/lib/queries";
import type { AuditEvent } from "@/lib/types";

const text = (value: unknown, fallback = "") =>
  value === undefined || value === null ? fallback : String(value);

const LABELS: Record<string, (e: AuditEvent) => string> = {
  "workspace.created": () => "created the workspace",
  "workspace.updated": () => "changed workspace settings",
  "member.added": (e) =>
    `added ${text(e.details.email, "a member")} as ${text(e.details.role, "member")}`,
  "member.role_changed": (e) => `changed a member's role to ${text(e.details.role)}`,
  "member.removed": () => "removed a member",
  "api_key.created": (e) => `created the API key ${text(e.details.name)}`,
  "api_key.revoked": (e) => `revoked the API key ${text(e.details.name)}`,
  "workflow.created": (e) => `created the workflow ${text(e.details.name)}`.trim(),
  "workflow.imported": (e) => `imported the workflow ${text(e.details.name)}`.trim(),
  "workflow.duplicated": (e) => `duplicated a workflow as ${text(e.details.name)}`.trim(),
  "workflow.updated": () => "changed a workflow's settings",
  "workflow.published": (e) => `published version ${text(e.details.version)} of a workflow`,
  "workflow.activated": (e) => `activated version ${text(e.details.version)} of a workflow`,
  "workflow.deactivated": () => "deactivated a workflow",
  "workflow.restored": (e) => `restored version ${text(e.details.version)} into a draft`,
  "workflow.deleted": (e) => `deleted the workflow ${text(e.details.name)}`.trim(),
  "credential.created": (e) => `stored the credential ${text(e.details.name)}`,
  "credential.updated": (e) => `updated the credential ${text(e.details.name)}`,
  "credential.deleted": (e) => `deleted the credential ${text(e.details.name)}`,
  "variable.saved": () => "saved a variable",
  "variable.deleted": () => "deleted a variable",
  "execution.cancelled": () => "cancelled an execution",
  "execution.resumed": () => "resumed an execution from its failed step",
  "execution.retried": () => "ran an execution again",
  "dead_letter.discarded": (e) => `discarded a dead letter from ${text(e.details.node, "a step")}`,
  "event.published": (e) => `published the event ${text(e.details.name)}`,
};

function target(event: AuditEvent, workspace: string): string | null {
  if (!event.target_id) return null;
  if (event.target_type === "workflow" && event.action !== "workflow.deleted") {
    return `/w/${workspace}/workflows/${event.target_id}`;
  }
  if (event.target_type === "execution") return `/w/${workspace}/executions/${event.target_id}`;
  return null;
}

export function AuditPanel({ workspace }: { workspace: string }) {
  const audit = useAudit(workspace);
  if (audit.error) return <ErrorNotice message={audit.error.message} />;
  if (!audit.data) return <Skeleton className="h-40" />;
  const events = audit.data.items;
  return (
    <Card>
      <p className="border-border text-muted-foreground border-b px-5 py-3.5 text-[13px]">
        Every change to workflows, credentials, people and keys, newest first. The log is append
        only.
      </p>
      {events.length ? (
        <ol className="divide-border divide-y" data-testid="audit-log">
          {events.map((event) => {
            const href = target(event, workspace);
            const label = (LABELS[event.action] ?? (() => event.action))(event);
            return (
              <li
                key={event.id}
                className="flex items-start justify-between gap-4 px-5 py-3 text-[13px]"
              >
                <p className="min-w-0">
                  <span className="font-medium">
                    {event.actor_name ??
                      (event.actor_type === "system" ? "The system" : "An API key")}
                  </span>{" "}
                  {href ? (
                    <Link
                      href={href}
                      className="text-muted-foreground hover:text-foreground underline-offset-2 hover:underline"
                    >
                      {label}
                    </Link>
                  ) : (
                    <span className="text-muted-foreground">{label}</span>
                  )}
                  <span className="text-subtle ml-2 font-mono text-[11px]">{event.action}</span>
                </p>
                <time
                  dateTime={event.created_at}
                  title={formatDateTime(event.created_at)}
                  className="text-subtle shrink-0 text-xs"
                >
                  {formatRelative(event.created_at)}
                </time>
              </li>
            );
          })}
        </ol>
      ) : (
        <EmptyState icon={<History />} title="No activity yet" />
      )}
    </Card>
  );
}
