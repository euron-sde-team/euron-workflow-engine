"use client";

import { FileUp, LayoutTemplate, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { ErrorNotice } from "@/components/ui/feedback";
import { Input, Label, Textarea } from "@/components/ui/input";
import { useCreateWorkflow, useImportWorkflow } from "@/lib/queries";

function NewWorkflowForm({ workspace, onDone }: { workspace: string; onDone: () => void }) {
  const router = useRouter();
  const create = useCreateWorkflow(workspace);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    const workflow = await create.mutateAsync({ name, description });
    onDone();
    router.push(`/w/${workspace}/workflows/${workflow.id}`);
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="space-y-1.5">
        <Label htmlFor="new-workflow-name">Name</Label>
        <Input id="new-workflow-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Sync new orders to the warehouse" required autoFocus />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="new-workflow-description">Description</Label>
        <Textarea id="new-workflow-description" rows={3} value={description} onChange={(e) => setDescription(e.target.value)} />
      </div>
      {create.error ? <ErrorNotice message={create.error.message} /> : null}
      <DialogFooter className="justify-between">
        <Button asChild variant="link" size="sm">
          <Link href={`/w/${workspace}/templates`}>
            <LayoutTemplate /> Start from a template
          </Link>
        </Button>
        <Button type="submit" disabled={!name.trim() || create.isPending} data-testid="create-workflow">
          Create
        </Button>
      </DialogFooter>
    </form>
  );
}

export function NewWorkflowButton({ workspace }: { workspace: string }) {
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Button onClick={() => setOpen(true)} data-testid="new-workflow">
        <Plus /> New workflow
      </Button>
      <DialogContent title="New workflow" description="It starts with a manual trigger; add nodes on the canvas.">
        <NewWorkflowForm workspace={workspace} onDone={() => setOpen(false)} />
      </DialogContent>
    </Dialog>
  );
}

export function ImportButton({ workspace }: { workspace: string }) {
  const router = useRouter();
  const importer = useImportWorkflow(workspace);
  const input = useRef<HTMLInputElement>(null);

  async function onFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    try {
      const document: unknown = JSON.parse(await file.text());
      const result = await importer.mutateAsync(document);
      if (result.unresolved_credentials.length) {
        toast.warning("Imported. Some credentials need choosing.", {
          description: result.unresolved_credentials.map((c) => `${c.name} (${c.type})`).join(", "),
        });
      } else {
        toast.success(`Imported "${result.workflow.name}"`);
      }
      router.push(`/w/${workspace}/workflows/${result.workflow.id}`);
    } catch (error) {
      toast.error("That file could not be imported", {
        description: error instanceof Error ? error.message : undefined,
      });
    }
  }

  return (
    <>
      <input ref={input} type="file" accept="application/json,.json" className="sr-only" aria-label="Workflow file" onChange={onFile} />
      <Button variant="secondary" onClick={() => input.current?.click()} disabled={importer.isPending}>
        <FileUp /> Import
      </Button>
    </>
  );
}
