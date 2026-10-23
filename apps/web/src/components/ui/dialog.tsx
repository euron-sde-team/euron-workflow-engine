"use client";

import { X } from "lucide-react";
import { Dialog as DialogPrimitive } from "radix-ui";
import type { ComponentProps, ReactNode } from "react";

import { cn } from "@/lib/cn";

export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;

export function DialogContent({
  className,
  children,
  title,
  description,
  ...props
}: ComponentProps<typeof DialogPrimitive.Content> & { title: ReactNode; description?: ReactNode }) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="data-[state=open]:animate-fade-in fixed inset-0 z-50 bg-black/40 backdrop-blur-[1px]" />
      <DialogPrimitive.Content
        className={cn(
          "border-border bg-card data-[state=open]:animate-fade-in fixed top-1/2 left-1/2 z-50 w-[min(92vw,30rem)] -translate-x-1/2 -translate-y-1/2 rounded-2xl border p-5 shadow-md",
          className,
        )}
        {...props}
      >
        <div className="mb-4 pr-8">
          <DialogPrimitive.Title className="text-base font-semibold tracking-tight">
            {title}
          </DialogPrimitive.Title>
          {description ? (
            <DialogPrimitive.Description className="text-muted-foreground mt-1 text-[13px]">
              {description}
            </DialogPrimitive.Description>
          ) : (
            <DialogPrimitive.Description className="sr-only">{title}</DialogPrimitive.Description>
          )}
        </div>
        {children}
        <DialogPrimitive.Close
          className="text-muted-foreground hover:bg-muted hover:text-foreground absolute top-4 right-4 rounded-md p-1 transition-colors"
          aria-label="Close"
        >
          <X className="size-4" />
        </DialogPrimitive.Close>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

export function DialogFooter({ className, ...props }: ComponentProps<"div">) {
  return <div className={cn("mt-5 flex justify-end gap-2", className)} {...props} />;
}
