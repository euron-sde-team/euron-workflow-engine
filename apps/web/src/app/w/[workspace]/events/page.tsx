"use client";

import { ChevronRight, RadioTower, Search, Send } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useDeferredValue, useState, type FormEvent } from "react";
import { toast } from "sonner";

import { JsonView } from "@/components/json-view";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorNotice, Skeleton, Spinner } from "@/components/ui/feedback";
import { FieldHint, Input, Label, Textarea } from "@/components/ui/input";
import { PageBody, PageHeader } from "@/components/ui/page";
import { cn } from "@/lib/cn";
import { formatDateTime, formatRelative, shortId } from "@/lib/format";
import { canEdit, useCurrentWorkspace, useEvents, usePublishEvent } from "@/lib/queries";
import type { BusEvent } from "@/lib/types";

const SOURCE_TONE = { api: "primary", workflow: "info", system: "warning" } as const;

function PublishForm({ workspace }: { workspace: string }) {
  const publish = usePublishEvent(workspace);
  const [name, setName] = useState("");
  const [payload, setPayload] = useState('{\n  "sku": "TENT-2P",\n  "on_hand": 3\n}');
  const [parseError, setParseError] = useState<string | null>(null);

  function submit(event: FormEvent) {
    event.preventDefault();
    let parsed: unknown;
    try {
      parsed = payload.trim() ? JSON.parse(payload) : {};
      setParseError(null);
    } catch (exc) {
      setParseError(exc instanceof Error ? exc.message : "Not valid JSON");
      return;
    }
    publish.mutate(
      { name: name.trim(), payload: parsed },
      {
        onSuccess: (result) =>
          toast.success(
            result.matched
              ? `Started ${result.matched} workflow${result.matched === 1 ? "" : "s"}`
              : "Published. No active workflow listens to it.",
          ),
      },
    );
  }

  return (
    <Card className="order-first self-start lg:order-none">
      <CardHeader>
        <div>
          <CardTitle>Publish an event</CardTitle>
          <CardDescription>
            Starts every active workflow with a matching event trigger.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="event-name">Name</Label>
            <Input
              id="event-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="inventory.low"
              className="font-mono"
              pattern="[a-z0-9][a-z0-9_.\-]{0,118}[a-z0-9]"
              required
            />
            <FieldHint>
              Lowercase, dot separated. Triggers can match a prefix like inventory.*
            </FieldHint>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="event-payload">Payload</Label>
            <Textarea
              id="event-payload"
              rows={6}
              className="font-mono text-[12px]"
              value={payload}
              onChange={(e) => setPayload(e.target.value)}
              spellCheck={false}
            />
            {parseError ? <p className="text-danger text-xs">JSON: {parseError}</p> : null}
          </div>
          {publish.error ? <ErrorNotice message={publish.error.message} /> : null}
          <Button
            type="submit"
            disabled={publish.isPending || !name.trim()}
            data-testid="publish-event"
          >
            {publish.isPending ? <Spinner className="text-primary-foreground" /> : <Send />}
            Publish
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

function EventRow({ event, workspace }: { event: BusEvent; workspace: string }) {
  const [open, setOpen] = useState(false);
  return (
    <li>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="hover:bg-muted/40 flex w-full items-center gap-3 px-5 py-3 text-left transition-colors"
      >
        <ChevronRight
          className={cn("text-subtle size-4 shrink-0 transition-transform", open && "rotate-90")}
          aria-hidden
        />
        <span className="min-w-0 flex-1">
          <span className="block truncate font-mono text-[13px] font-medium">{event.name}</span>
          <span className="text-muted-foreground text-[12px]">
            {event.matched
              ? `Started ${event.matched} workflow${event.matched === 1 ? "" : "s"}`
              : "No listener"}
            {event.depth ? `, chain depth ${event.depth}` : ""}
          </span>
        </span>
        <Badge tone={SOURCE_TONE[event.source]}>{event.source}</Badge>
        <span
          className="text-muted-foreground hidden w-28 text-right text-[12px] sm:block"
          title={formatDateTime(event.created_at)}
        >
          {formatRelative(event.created_at)}
        </span>
      </button>
      {open ? (
        <div className="space-y-2 px-5 pb-4 pl-12">
          {event.source_execution_id ? (
            <p className="text-[12.5px]">
              Published by execution{" "}
              <Link
                href={`/w/${workspace}/executions/${event.source_execution_id}`}
                className="text-primary font-mono hover:underline"
              >
                {shortId(event.source_execution_id)}
              </Link>
            </p>
          ) : null}
          <JsonView value={event.payload} label={`Payload of ${event.name}`} empty="No payload." />
        </div>
      ) : null}
    </li>
  );
}

export default function EventsPage() {
  const { workspace } = useParams<{ workspace: string }>();
  const current = useCurrentWorkspace(workspace);
  const [filter, setFilter] = useState("");
  const deferred = useDeferredValue(filter.trim());
  const events = useEvents(workspace, deferred);

  return (
    <PageBody>
      <PageHeader
        title="Event bus"
        description="Named events connect workflows: one publishes, every subscriber starts. The engine itself publishes execution.succeeded and execution.failed as runs finish."
      />
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <Card className="min-w-0 self-start overflow-hidden">
          <div className="border-border flex items-center gap-3 border-b px-5 py-3">
            <div className="relative flex-1">
              <Search
                className="text-subtle pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2"
                aria-hidden
              />
              <Input
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Filter by exact name, for example order.paid"
                className="pl-9"
                aria-label="Filter events by name"
              />
            </div>
          </div>
          {events.error ? <ErrorNotice message={events.error.message} className="m-5" /> : null}
          {!events.data ? (
            <Skeleton className="m-5 h-64" />
          ) : events.data.items.length === 0 ? (
            <EmptyState
              icon={<RadioTower />}
              title={deferred ? "No event with that name" : "No events yet"}
              description="Events published by the API, by workflows or by the system appear here."
            />
          ) : (
            <ol className="divide-border divide-y" data-testid="event-list">
              {events.data.items.map((event) => (
                <EventRow key={event.id} event={event} workspace={workspace} />
              ))}
            </ol>
          )}
        </Card>
        {canEdit(current?.role) ? <PublishForm workspace={workspace} /> : null}
      </div>
    </PageBody>
  );
}
