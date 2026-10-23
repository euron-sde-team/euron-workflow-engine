"use client";

import { useParams } from "next/navigation";
import type { ReactNode } from "react";

import { AppShell } from "@/components/shell/app-shell";

export default function WorkspaceLayout({ children }: { children: ReactNode }) {
  const { workspace } = useParams<{ workspace: string }>();
  return <AppShell workspace={workspace}>{children}</AppShell>;
}
