"use client";

import {
  Archive,
  Blocks,
  Gauge,
  History,
  KeyRound,
  LayoutTemplate,
  Menu,
  Radio,
  Settings,
  Workflow as WorkflowIcon,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { Wordmark } from "@/components/brand";
import { UserMenu } from "@/components/shell/user-menu";
import { WorkspaceSwitcher } from "@/components/shell/workspace-switcher";
import { Button } from "@/components/ui/button";
import { EmptyState, Spinner } from "@/components/ui/feedback";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useMe } from "@/lib/queries";
import { runtimeEnv } from "@/lib/runtime-env";
import { LAST_WORKSPACE_KEY, writeLocal } from "@/lib/storage";
import type { Me, WorkspaceSummary } from "@/lib/types";

const NAV = [
  { segment: "dashboard", label: "Dashboard", icon: Gauge },
  { segment: "workflows", label: "Workflows", icon: WorkflowIcon },
  { segment: "executions", label: "Executions", icon: History },
  { segment: "templates", label: "Templates", icon: LayoutTemplate },
] as const;

const OPERATE = [
  { segment: "credentials", label: "Credentials", icon: KeyRound },
  { segment: "events", label: "Event bus", icon: Radio },
  { segment: "dead-letters", label: "Dead letters", icon: Archive },
  { segment: "settings", label: "Settings", icon: Settings },
] as const;

function NavLink({
  href,
  active,
  label,
  icon: Icon,
  onNavigate,
}: {
  href: string;
  active: boolean;
  label: string;
  icon: typeof Blocks;
  onNavigate?: () => void;
}) {
  return (
    <Link
      href={href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-[13.5px] transition-colors [&_svg]:size-4",
        active
          ? "bg-card font-medium text-foreground shadow-sm ring-1 ring-border"
          : "text-muted-foreground hover:bg-muted hover:text-foreground",
      )}
    >
      <Icon className={active ? "text-primary" : ""} />
      {label}
    </Link>
  );
}

function Sidebar({ me, current, onNavigate }: { me: Me; current: WorkspaceSummary; onNavigate?: () => void }) {
  const pathname = usePathname();
  const base = `/w/${current.slug}`;
  const isActive = (segment: string) => pathname.startsWith(`${base}/${segment}`);
  return (
    <div className="flex h-full w-60 flex-col border-r border-sidebar-border bg-sidebar">
      <div className="px-3 pb-2 pt-3">
        <WorkspaceSwitcher current={current} all={me.workspaces} />
      </div>
      <nav className="mt-2 space-y-0.5 px-3" aria-label="Build">
        {NAV.map((item) => (
          <NavLink
            key={item.segment}
            href={`${base}/${item.segment}`}
            active={isActive(item.segment)}
            label={item.label}
            icon={item.icon}
            onNavigate={onNavigate}
          />
        ))}
      </nav>
      <p className="mt-5 px-5 pb-1.5 text-[11px] font-medium uppercase tracking-wider text-subtle">Operate</p>
      <nav className="space-y-0.5 px-3" aria-label="Operate">
        {OPERATE.map((item) => (
          <NavLink
            key={item.segment}
            href={`${base}/${item.segment}`}
            active={isActive(item.segment)}
            label={item.label}
            icon={item.icon}
            onNavigate={onNavigate}
          />
        ))}
      </nav>
      <div className="mt-auto border-t border-sidebar-border p-3">
        <UserMenu user={me.user} />
      </div>
    </div>
  );
}

export function AppShell({ workspace, children }: { workspace: string; children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const me = useMe();
  const [drawer, setDrawer] = useState(false);
  const unauthorized = me.error instanceof ApiError && me.error.status === 401;
  const current = me.data?.workspaces.find((w) => w.slug === workspace || w.id === workspace);

  useEffect(() => {
    if (unauthorized) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [unauthorized, pathname, router]);

  useEffect(() => {
    if (current) writeLocal(LAST_WORKSPACE_KEY, current.slug);
  }, [current]);

  if (me.isLoading || unauthorized) {
    return (
      <div className="flex h-dvh items-center justify-center">
        <Spinner className="size-5" />
      </div>
    );
  }
  if (me.error || !me.data) {
    return <EmptyState title="WorkflowEngine is unreachable" description={me.error?.message ?? "Try again shortly."} />;
  }
  if (!current) {
    return (
      <EmptyState
        className="h-dvh"
        title="Workspace not found"
        description="It does not exist, or you are not a member."
        action={
          <Button asChild variant="secondary">
            <Link href="/">Go to my workspaces</Link>
          </Button>
        }
      />
    );
  }

  return (
    <div className="flex h-dvh overflow-hidden">
      <aside className="hidden lg:block">
        <Sidebar me={me.data} current={current} />
      </aside>
      {drawer ? (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button
            type="button"
            aria-label="Close menu"
            className="absolute inset-0 bg-black/40"
            onClick={() => setDrawer(false)}
          />
          <div className="relative h-full w-60 animate-fade-in">
            <Sidebar me={me.data} current={current} onNavigate={() => setDrawer(false)} />
          </div>
        </div>
      ) : null}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 items-center justify-between border-b border-border px-3 lg:hidden">
          <Button variant="ghost" size="icon-sm" aria-label="Open menu" onClick={() => setDrawer(true)}>
            {drawer ? <X /> : <Menu />}
          </Button>
          <Wordmark name={runtimeEnv().productName} className="[&_svg]:size-6" />
          <span className="size-8" />
        </header>
        <main className="scroll-quiet min-h-0 flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  );
}
