"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { WorkflowEditor } from "@/components/editor/editor";
import { Button } from "@/components/ui/button";
import { EmptyState, Spinner } from "@/components/ui/feedback";
import { useCurrentWorkspace, useWorkflow } from "@/lib/queries";

export default function WorkflowPage() {
  const { workspace, id } = useParams<{ workspace: string; id: string }>();
  const workflow = useWorkflow(workspace, id);
  const current = useCurrentWorkspace(workspace);

  if (workflow.error) {
    return (
      <EmptyState
        className="h-full"
        title="Workflow not found"
        description={workflow.error.message}
        action={
          <Button asChild variant="secondary">
            <Link href={`/w/${workspace}/workflows`}>All workflows</Link>
          </Button>
        }
      />
    );
  }
  if (!workflow.data || !current) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner className="size-5" />
      </div>
    );
  }
  return (
    <div className="h-full">
      <WorkflowEditor workspace={workspace} workflow={workflow.data} role={current.role} />
    </div>
  );
}
