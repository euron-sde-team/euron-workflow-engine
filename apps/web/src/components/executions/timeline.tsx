"use client";

import { STATUS } from "@/components/status";
import { cn } from "@/lib/cn";
import { timeline as layoutTimeline } from "@/lib/executions";
import { formatDuration } from "@/lib/format";
import type { Execution } from "@/lib/types";

const BAR: Record<string, string> = {
  succeeded: "bg-success/80",
  failed: "bg-danger",
  running: "bg-info animate-pulse",
  waiting: "bg-warning/70 bg-[repeating-linear-gradient(45deg,transparent_0_4px,rgb(255_255_255/0.25)_4px_8px)]",
  queued: "bg-subtle/50",
  cancelled: "bg-subtle/60",
  skipped: "bg-input",
};

/** A Gantt view of the steps that started, on one time axis. */
export function Timeline({
  execution,
  now,
  selectedStep,
  onSelectStep,
}: {
  execution: Execution;
  now: number;
  selectedStep: string | null;
  onSelectStep: (stepId: string) => void;
}) {
  const { rows, spanMs, skipped } = layoutTimeline(execution, now);
  if (!rows.length) {
    return <p className="px-5 py-6 text-[13px] text-muted-foreground">No step has started yet.</p>;
  }
  const ticks = [0, 0.25, 0.5, 0.75, 1];
  return (
    <div className="px-5 pb-4" data-testid="timeline">
      <div className="ml-[38%] flex justify-between pb-1.5 text-[11px] tabular-nums text-subtle sm:ml-[30%]">
        {ticks.map((tick) => (
          <span key={tick}>{formatDuration(spanMs * tick)}</span>
        ))}
      </div>
      <ol className="max-h-[26rem] space-y-0.5 overflow-y-auto">
        {rows.map((row) => {
          const status = STATUS[row.step.status];
          return (
            <li key={row.step.id}>
              <button
                type="button"
                onClick={() => onSelectStep(row.step.id)}
                className={cn(
                  "group flex w-full items-center gap-3 rounded-md px-1.5 py-1 text-left transition-colors hover:bg-muted",
                  selectedStep === row.step.id && "bg-accent hover:bg-accent",
                )}
                aria-label={`${row.label}: ${status.label}, ${formatDuration(row.step.duration_ms)}`}
              >
                <span className="w-[38%] truncate text-[12.5px] sm:w-[30%]">{row.label}</span>
                <span className="relative h-4 flex-1 rounded-sm bg-muted/60">
                  <span
                    className={cn("absolute top-0 h-full rounded-sm", BAR[row.step.status])}
                    style={{ left: `${row.offset * 100}%`, width: `${row.width * 100}%` }}
                  />
                </span>
                <span className="w-16 shrink-0 text-right text-[11.5px] tabular-nums text-muted-foreground">
                  {row.step.duration_ms !== null ? formatDuration(row.step.duration_ms) : status.label}
                </span>
              </button>
            </li>
          );
        })}
      </ol>
      {skipped ? (
        <p className="mt-2 text-[12px] text-subtle">
          {skipped} skipped step{skipped === 1 ? "" : "s"} on branches that did not run.
        </p>
      ) : null}
    </div>
  );
}
