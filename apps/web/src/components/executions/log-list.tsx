"use client";

import { ChevronRight } from "lucide-react";
import { useState } from "react";

import { cn } from "@/lib/cn";
import { formatTime, prettyJson } from "@/lib/format";
import type { LogLine } from "@/lib/types";

const LEVEL: Record<LogLine["level"], string> = {
  debug: "text-subtle",
  info: "text-info",
  warn: "text-warning",
  error: "text-danger",
};

function Line({ line, stepName }: { line: LogLine; stepName?: string }) {
  const [open, setOpen] = useState(false);
  const hasData = Object.keys(line.data).length > 0;
  return (
    <li className="border-border/60 border-b last:border-0">
      <button
        type="button"
        disabled={!hasData}
        onClick={() => setOpen((v) => !v)}
        className="enabled:hover:bg-muted/60 flex w-full items-start gap-2.5 px-3 py-1.5 text-left font-mono text-[12px] leading-5"
        aria-expanded={hasData ? open : undefined}
      >
        <ChevronRight
          className={cn(
            "text-subtle mt-1 size-3 shrink-0 transition-transform",
            open && "rotate-90",
            !hasData && "invisible",
          )}
          aria-hidden
        />
        <span className="text-subtle shrink-0 tabular-nums">{formatTime(line.created_at)}</span>
        <span className={cn("w-10 shrink-0 font-semibold uppercase", LEVEL[line.level])}>
          {line.level}
        </span>
        {stepName ? <span className="text-muted-foreground shrink-0">[{stepName}]</span> : null}
        <span className="min-w-0 flex-1 break-words whitespace-pre-wrap">{line.message}</span>
      </button>
      {open ? (
        <pre className="bg-muted/70 text-muted-foreground mx-3 mb-2 overflow-x-auto rounded-md p-2 font-mono text-[11.5px]">
          {prettyJson(line.data)}
        </pre>
      ) : null}
    </li>
  );
}

export function LogList({
  lines,
  stepNames,
  empty = "No log lines.",
}: {
  lines: LogLine[];
  stepNames?: Map<string, string>;
  empty?: string;
}) {
  if (!lines.length) return <p className="text-subtle px-1 text-[12.5px]">{empty}</p>;
  return (
    <ol
      className="scroll-quiet border-border bg-card max-h-[28rem] overflow-y-auto rounded-lg border"
      data-testid="log-list"
    >
      {lines.map((line) => (
        <Line
          key={line.id}
          line={line}
          stepName={line.step_id ? stepNames?.get(line.step_id) : undefined}
        />
      ))}
    </ol>
  );
}
