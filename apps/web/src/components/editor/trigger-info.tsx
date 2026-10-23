"use client";

import { CalendarClock, Info, Webhook } from "lucide-react";

import { CopyField } from "@/components/settings/copy-field";
import { formatDateTime, formatRelative } from "@/lib/format";
import type { NodeSpec, TriggerInfo } from "@/lib/types";

const text = (value: unknown, fallback: string) =>
  typeof value === "string" && value ? value : fallback;

/** How an external system reaches this trigger, and when a schedule fires next. */
export function TriggerInfoBox({
  node,
  trigger,
  active,
}: {
  node: NodeSpec;
  trigger: TriggerInfo | undefined;
  active: boolean;
}) {
  if (node.type === "trigger.webhook") {
    const auth = text(node.config.auth, "hmac_sha256");
    const signatureHeader = text(node.config.signature_header, "X-Signature");
    const prefix =
      typeof node.config.signature_prefix === "string" ? node.config.signature_prefix : "sha256=";
    const timestampHeader = text(node.config.timestamp_header, "");
    return (
      <div
        className="border-border bg-muted/40 mb-4 space-y-2.5 rounded-xl border p-3"
        data-testid="webhook-info"
      >
        <p className="flex items-center gap-2 text-[12.5px] font-medium">
          <Webhook className="text-muted-foreground size-4" aria-hidden />
          {trigger?.method ?? "POST"} endpoint
        </p>
        {trigger?.url ? (
          <CopyField value={trigger.url} label="Webhook URL" />
        ) : (
          <p className="text-muted-foreground text-[12px]">Set a path to get a URL.</p>
        )}
        <p className="text-muted-foreground text-[12px] leading-relaxed">
          {auth === "hmac_sha256" ? (
            <>
              Sign the raw body with HMAC-SHA256 and the webhook secret, then send{" "}
              <code className="font-mono">
                {signatureHeader}: {prefix}&lt;hex&gt;
              </code>
              {timestampHeader ? (
                <>
                  {" "}
                  over <code className="font-mono">&lt;timestamp&gt;.&lt;body&gt;</code> with the
                  time in <code className="font-mono">{timestampHeader}</code>
                </>
              ) : null}
              .
            </>
          ) : auth === "bearer" ? (
            <>
              Send the webhook secret as{" "}
              <code className="font-mono">
                {text(node.config.token_header, "Authorization")}: Bearer ...
              </code>
            </>
          ) : (
            <>Anyone with the URL can start this workflow. Prefer a signed webhook.</>
          )}{" "}
          Repeated{" "}
          <code className="font-mono">
            {text(node.config.idempotency_header, "Idempotency-Key")}
          </code>{" "}
          values return the first execution.
        </p>
        {!active ? (
          <p className="text-warning flex items-center gap-1.5 text-[12px]">
            <Info className="size-3.5" aria-hidden />
            Publish and activate the workflow before the URL accepts requests.
          </p>
        ) : null}
      </div>
    );
  }
  if (node.type === "trigger.cron" || node.type === "trigger.interval") {
    return (
      <div
        className="border-border bg-muted/40 mb-4 space-y-1 rounded-xl border p-3 text-[12.5px]"
        data-testid="schedule-info"
      >
        <p className="flex items-center gap-2 font-medium">
          <CalendarClock className="text-muted-foreground size-4" aria-hidden />
          {trigger?.summary ?? "Schedule"}
        </p>
        <p className="text-muted-foreground text-[12px]">
          {active && trigger?.next_fire_at
            ? `Next run ${formatRelative(trigger.next_fire_at)}, ${formatDateTime(trigger.next_fire_at)}`
            : "Runs once the workflow is published and active. Only one scheduler fires it, even with several replicas."}
        </p>
      </div>
    );
  }
  return null;
}
