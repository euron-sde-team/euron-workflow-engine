import { CalendarClock, Hand, RadioTower, RotateCcw, Timer, Webhook, type LucideIcon } from "lucide-react";

import { cn } from "@/lib/cn";

const TRIGGERS: Record<string, { label: string; icon: LucideIcon }> = {
  manual: { label: "Manual", icon: Hand },
  webhook: { label: "Webhook", icon: Webhook },
  cron: { label: "Schedule", icon: CalendarClock },
  interval: { label: "Interval", icon: Timer },
  event: { label: "Event", icon: RadioTower },
  retry: { label: "Retry", icon: RotateCcw },
};

export function TriggerLabel({ kind, className }: { kind: string; className?: string }) {
  const entry = TRIGGERS[kind] ?? { label: kind, icon: Hand };
  const Icon = entry.icon;
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-[12.5px] text-muted-foreground", className)}>
      <Icon className="size-3.5" aria-hidden />
      {entry.label}
    </span>
  );
}
