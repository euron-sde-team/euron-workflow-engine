import { Loader2 } from "lucide-react";
import type { ComponentProps, ReactNode } from "react";

import { cn } from "@/lib/cn";

export function Skeleton({ className, ...props }: ComponentProps<"div">) {
  return <div className={cn("animate-pulse rounded-lg bg-muted", className)} {...props} />;
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn("size-4 animate-spin text-muted-foreground", className)} aria-hidden />;
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: {
  icon?: ReactNode;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center justify-center px-6 py-14 text-center", className)}>
      {icon ? (
        <div className="mb-3 flex size-11 items-center justify-center rounded-xl bg-accent text-accent-foreground [&_svg]:size-5">
          {icon}
        </div>
      ) : null}
      <p className="text-[15px] font-semibold tracking-tight">{title}</p>
      {description ? <p className="mt-1 max-w-sm text-[13px] text-muted-foreground">{description}</p> : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

export function ErrorNotice({ message, className }: { message: string; className?: string }) {
  return (
    <div role="alert" className={cn("rounded-lg border border-danger/30 bg-danger-soft px-3 py-2 text-[13px] text-danger", className)}>
      {message}
    </div>
  );
}
