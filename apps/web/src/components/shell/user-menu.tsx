"use client";

import { LogOut, Moon, Sun } from "lucide-react";
import { useRouter } from "next/navigation";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { initials } from "@/lib/format";
import { useLogout } from "@/lib/queries";
import { useTheme } from "@/lib/theme";
import type { User } from "@/lib/types";

export function UserMenu({ user }: { user: User }) {
  const router = useRouter();
  const logout = useLogout();
  const [theme, toggleTheme] = useTheme();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="hover:bg-muted flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 text-left transition-colors"
          aria-label="Account menu"
        >
          <span className="bg-muted text-foreground ring-border flex size-7 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold ring-1">
            {initials(user.name)}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[13px] leading-tight font-medium">
              {user.name}
            </span>
            <span className="text-muted-foreground block truncate text-[11.5px]">{user.email}</span>
          </span>
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" side="top" className="w-60">
        <DropdownMenuLabel>{user.email}</DropdownMenuLabel>
        <DropdownMenuItem
          onSelect={(event) => {
            event.preventDefault();
            toggleTheme();
          }}
        >
          {theme === "dark" ? <Sun /> : <Moon />} {theme === "dark" ? "Light theme" : "Dark theme"}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onSelect={async () => {
            await logout.mutateAsync().catch(() => undefined);
            router.replace("/login");
          }}
        >
          <LogOut /> Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
