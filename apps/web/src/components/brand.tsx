import { cn } from "@/lib/cn";

/** Two nodes joined by an edge: the smallest possible workflow. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" aria-hidden className={cn("size-7", className)}>
      <rect width="64" height="64" rx="16" fill="var(--primary)" />
      <path
        d="M24 21h8a9 9 0 0 1 9 9v6"
        fill="none"
        stroke="var(--primary-foreground)"
        strokeWidth="5"
        strokeLinecap="round"
      />
      <circle cx="19" cy="21" r="6.5" fill="var(--primary-foreground)" />
      <circle cx="41" cy="43" r="6.5" fill="var(--primary-foreground)" />
      <circle cx="41" cy="43" r="2.5" fill="var(--primary)" />
    </svg>
  );
}

export function Wordmark({ name, className }: { name: string; className?: string }) {
  return (
    <span className={cn("flex items-center gap-2.5", className)}>
      <BrandMark />
      <span className="text-[15px] font-semibold tracking-tight">{name}</span>
    </span>
  );
}
