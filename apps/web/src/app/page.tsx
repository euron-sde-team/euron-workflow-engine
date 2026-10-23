"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { Spinner } from "@/components/ui/feedback";
import { ApiError } from "@/lib/api";
import { useMe } from "@/lib/queries";
import { LAST_WORKSPACE_KEY, readLocal } from "@/lib/storage";
import { pickWorkspace } from "@/lib/workspace-choice";

export default function Home() {
  const router = useRouter();
  const me = useMe();

  useEffect(() => {
    if (me.error instanceof ApiError && me.error.status === 401) {
      router.replace("/login");
      return;
    }
    if (!me.data) return;
    const target = pickWorkspace(me.data.workspaces, readLocal(LAST_WORKSPACE_KEY));
    router.replace(target ? `/w/${target}/dashboard` : "/welcome");
  }, [me.data, me.error, router]);

  return (
    <main className="flex min-h-dvh items-center justify-center">
      <Spinner className="size-5" />
    </main>
  );
}
