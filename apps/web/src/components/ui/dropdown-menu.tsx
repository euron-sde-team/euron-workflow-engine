"use client";

import { DropdownMenu as Menu } from "radix-ui";
import type { ComponentProps } from "react";

import { cn } from "@/lib/cn";

export const DropdownMenu = Menu.Root;
export const DropdownMenuTrigger = Menu.Trigger;

export function DropdownMenuContent({
  className,
  sideOffset = 6,
  ...props
}: ComponentProps<typeof Menu.Content>) {
  return (
    <Menu.Portal>
      <Menu.Content
        sideOffset={sideOffset}
        className={cn(
          "border-border bg-card data-[state=open]:animate-fade-in z-50 min-w-48 overflow-hidden rounded-xl border p-1 text-sm shadow-md",
          className,
        )}
        {...props}
      />
    </Menu.Portal>
  );
}

export function DropdownMenuItem({
  className,
  destructive,
  ...props
}: ComponentProps<typeof Menu.Item> & { destructive?: boolean }) {
  return (
    <Menu.Item
      className={cn(
        "data-[highlighted]:bg-muted [&_svg]:text-muted-foreground flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-1.5 transition-colors outline-none select-none data-[disabled]:pointer-events-none data-[disabled]:opacity-50 [&_svg]:size-4",
        destructive && "text-danger [&_svg]:text-danger",
        className,
      )}
      {...props}
    />
  );
}

export function DropdownMenuLabel({ className, ...props }: ComponentProps<typeof Menu.Label>) {
  return (
    <Menu.Label
      className={cn("text-muted-foreground px-2.5 py-1.5 text-xs", className)}
      {...props}
    />
  );
}

export function DropdownMenuSeparator({
  className,
  ...props
}: ComponentProps<typeof Menu.Separator>) {
  return <Menu.Separator className={cn("bg-border my-1 h-px", className)} {...props} />;
}
