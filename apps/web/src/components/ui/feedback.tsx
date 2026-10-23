import { Loader2 } from "lucide-react";
import type { ComponentProps, ReactNode } from "react";

import { cn } from "@/lib/cn";

export function Skeleton({ className, ...props }: ComponentProps<"div">) {
  return <div className={cn("bg-muted animate-pulse rounded-lg", className)} {...props} />;
}

export function Spinner({ className }: { className?: string }) {
  return (
    <Loader2 className={cn("text-muted-foreground size-4 animate-spin", className)} aria-hidden />
  );
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
    <div
      className={cn("flex flex-col items-center justify-center px-6 py-14 text-center", className)}
    >
      {icon ? (
        <div className="bg-accent text-accent-foreground mb-3 flex size-11 items-center justify-center rounded-xl [&_svg]:size-5">
          {icon}
        </div>
      ) : null}
      <p className="text-[15px] font-semibold tracking-tight">{title}</p>
      {description ? (
        <p className="text-muted-foreground mt-1 max-w-sm text-[13px]">{description}</p>
      ) : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

export function ErrorNotice({ message, className }: { message: string; className?: string }) {
  return (
    <div
      role="alert"
      className={cn(
        "border-danger/30 bg-danger-soft text-danger rounded-lg border px-3 py-2 text-[13px]",
        className,
      )}
    >
      {message}
    </div>
  );
}
