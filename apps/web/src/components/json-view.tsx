"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";

import { cn } from "@/lib/cn";
import { prettyJson } from "@/lib/format";

export function JsonView({
  value,
  className,
  empty = "Nothing here.",
  label,
}: {
  value: unknown;
  className?: string;
  empty?: string;
  label?: string;
}) {
  const [copied, setCopied] = useState(false);
  const text = prettyJson(value);
  if (value === undefined || value === null) {
    return <p className={cn("text-subtle px-1 text-[12.5px]", className)}>{empty}</p>;
  }
  return (
    <div className={cn("group relative", className)}>
      <pre
        className="scroll-quiet border-border bg-muted/60 text-foreground max-h-[28rem] overflow-auto rounded-lg border p-3 font-mono text-[12px] leading-relaxed"
        aria-label={label}
        tabIndex={0}
      >
        {text}
      </pre>
      <button
        type="button"
        onClick={() => {
          void navigator.clipboard?.writeText(text).then(() => {
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          });
        }}
        className="border-border bg-card text-muted-foreground hover:text-foreground absolute top-2 right-2 rounded-md border p-1 opacity-0 shadow-sm transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
        aria-label="Copy JSON"
      >
        {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
      </button>
    </div>
  );
}
