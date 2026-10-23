import Link from "next/link";

import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-3 p-6 text-center">
      <p className="font-mono text-sm text-subtle">404</p>
      <h1 className="text-2xl font-semibold tracking-tight">This page does not exist</h1>
      <p className="text-[14px] text-muted-foreground">The link may be old, or you may not have access.</p>
      <Button asChild className="mt-2">
        <Link href="/">Back to WorkflowEngine</Link>
      </Button>
    </main>
  );
}
