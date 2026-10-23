"use client";

import { Archive, ChevronRight, RotateCcw, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { JsonView } from "@/components/json-view";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorNotice, Skeleton } from "@/components/ui/feedback";
import { PageBody, PageHeader } from "@/components/ui/page";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/cn";
import { formatDateTime, formatRelative, shortId } from "@/lib/format";
import { canEdit, useCurrentWorkspace, useDeadLetterActions, useDeadLetters } from "@/lib/queries";
import type { DeadLetter } from "@/lib/types";

const STATUSES = [
  ["open", "Open"],
  ["retried", "Retried"],
  ["discarded", "Discarded"],
] as const;

function Letter({
  letter,
  workspace,
  editable,
}: {
  letter: DeadLetter;
  workspace: string;
  editable: boolean;
}) {
  const [open, setOpen] = useState(false);
  const actions = useDeadLetterActions(workspace);
  const busy = actions.retry.isPending || actions.discard.isPending;
  return (
    <li data-testid="dead-letter">
      {/* On narrow screens the actions wrap below the text instead of squeezing it. */}
      <div className="flex flex-wrap items-start gap-3 px-5 py-3.5">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          aria-label={open ? "Hide details" : "Show details"}
          className="text-subtle hover:text-foreground mt-0.5 rounded-md p-0.5"
        >
          <ChevronRight className={cn("size-4 transition-transform", open && "rotate-90")} />
        </button>
        <div className="min-w-0 flex-1 basis-64">
          <p className="flex flex-wrap items-center gap-x-2 text-[13.5px] font-medium">
            {letter.workflow_name || "Deleted workflow"}
            <span className="text-muted-foreground font-normal">at</span>
            {letter.node_name}
          </p>
          <p className="text-danger mt-0.5 text-[12.5px]">
            <span className="font-mono text-[11.5px]">{letter.error.code}</span>{" "}
            {letter.error.message}
          </p>
          <p className="text-muted-foreground mt-1 text-[12px]">
            <Link
              href={`/w/${workspace}/executions/${letter.execution_id}`}
              className="text-primary font-mono hover:underline"
            >
              {shortId(letter.execution_id)}
            </Link>{" "}
            &middot;{" "}
            <span title={formatDateTime(letter.created_at)}>
              {formatRelative(letter.created_at)}
            </span>
            {letter.resolved_at ? (
              <> &middot; resolved {formatRelative(letter.resolved_at)}</>
            ) : null}
          </p>
        </div>
        {letter.status !== "open" ? (
          <Badge tone={letter.status === "retried" ? "info" : "neutral"}>{letter.status}</Badge>
        ) : editable ? (
          <div className="ml-auto flex shrink-0 gap-2">
            <Button
              size="sm"
              variant="secondary"
              disabled={busy}
              onClick={() =>
                actions.discard.mutate(letter.id, {
                  onSuccess: () => toast.success("Discarded"),
                  onError: (error) => toast.error(error.message),
                })
              }
            >
              <Trash2 /> Discard
            </Button>
            <Button
              size="sm"
              disabled={busy}
              data-testid="retry-dead-letter"
              onClick={() =>
                actions.retry.mutate(letter.id, {
                  onSuccess: () => toast.success("Resumed from the failed step"),
                  onError: (error) => toast.error(error.message),
                })
              }
            >
              <RotateCcw /> Retry
            </Button>
          </div>
        ) : null}
      </div>
      {open ? (
        <div className="grid gap-3 px-5 pb-4 pl-12 lg:grid-cols-2">
          <div>
            <p className="text-subtle mb-1 text-[11.5px] font-medium tracking-wide uppercase">
              Input
            </p>
            <JsonView value={letter.input} label="Step input" empty="No input." />
          </div>
          <div>
            <p className="text-subtle mb-1 text-[11.5px] font-medium tracking-wide uppercase">
              Error
            </p>
            <JsonView value={letter.error} label="Error" />
          </div>
        </div>
      ) : null}
    </li>
  );
}

export default function DeadLettersPage() {
  const { workspace } = useParams<{ workspace: string }>();
  const current = useCurrentWorkspace(workspace);
  const [status, setStatus] = useState("open");
  const letters = useDeadLetters(workspace, status);
  return (
    <PageBody>
      <PageHeader
        title="Dead letters"
        description="Steps that failed after their last retry. Retry resumes the execution from that step; discard closes the letter."
      />
      <Tabs value={status} onValueChange={setStatus}>
        <TabsList>
          {STATUSES.map(([value, label]) => (
            <TabsTrigger key={value} value={value}>
              {label}
            </TabsTrigger>
          ))}
        </TabsList>
        {/* One panel per status, so every tab controls an element that exists. */}
        {STATUSES.map(([value]) => (
          <TabsContent key={value} value={value}>
            {value !== status ? null : letters.error ? (
              <ErrorNotice message={letters.error.message} />
            ) : !letters.data ? (
              <Skeleton className="h-64" />
            ) : letters.data.items.length === 0 ? (
              <Card>
                <EmptyState
                  icon={<Archive />}
                  title={
                    status === "open" ? "Nothing in the dead letter queue" : `No ${status} letters`
                  }
                  description="When a step runs out of retries and has no error branch, it lands here with its input."
                />
              </Card>
            ) : (
              <Card className="overflow-hidden">
                <ol className="divide-border divide-y">
                  {letters.data.items.map((letter) => (
                    <Letter
                      key={letter.id}
                      letter={letter}
                      workspace={workspace}
                      editable={canEdit(current?.role)}
                    />
                  ))}
                </ol>
              </Card>
            )}
          </TabsContent>
        ))}
      </Tabs>
    </PageBody>
  );
}
