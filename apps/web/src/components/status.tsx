import {
  Ban,
  CheckCircle2,
  Clock3,
  Hourglass,
  Loader2,
  MinusCircle,
  XCircle,
  type LucideIcon,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";
import type { ExecutionStatus, StepStatus } from "@/lib/types";

type Tone = "neutral" | "primary" | "success" | "warning" | "danger" | "outline" | "info";

export const STATUS: Record<
  ExecutionStatus | StepStatus,
  { label: string; tone: Tone; icon: LucideIcon }
> = {
  succeeded: { label: "Succeeded", tone: "success", icon: CheckCircle2 },
  failed: { label: "Failed", tone: "danger", icon: XCircle },
  running: { label: "Running", tone: "info", icon: Loader2 },
  queued: { label: "Queued", tone: "neutral", icon: Clock3 },
  waiting: { label: "Waiting", tone: "warning", icon: Hourglass },
  cancelled: { label: "Cancelled", tone: "neutral", icon: Ban },
  skipped: { label: "Skipped", tone: "outline", icon: MinusCircle },
};

export function StatusBadge({
  status,
  className,
}: {
  status: ExecutionStatus | StepStatus;
  className?: string;
}) {
  const { label, tone, icon: Icon } = STATUS[status];
  return (
    <Badge tone={tone} className={className}>
      <Icon className={cn(status === "running" && "animate-spin")} aria-hidden />
      {label}
    </Badge>
  );
}

/** A coloured dot for dense lists and the canvas. */
export function StatusDot({
  status,
  className,
}: {
  status: ExecutionStatus | StepStatus;
  className?: string;
}) {
  const color: Record<string, string> = {
    succeeded: "bg-success",
    failed: "bg-danger",
    running: "bg-info animate-pulse-dot",
    queued: "bg-subtle",
    waiting: "bg-warning",
    cancelled: "bg-subtle",
    skipped: "bg-input",
  };
  return (
    <span
      className={cn("inline-block size-2 shrink-0 rounded-full", color[status], className)}
      aria-hidden
    />
  );
}
