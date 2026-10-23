"use client";

import { FolderPlus } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Wordmark } from "@/components/brand";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ErrorNotice } from "@/components/ui/feedback";
import { Input, Label, Textarea } from "@/components/ui/input";
import { runtimeEnv } from "@/lib/runtime-env";
import { useCreateWorkspace } from "@/lib/queries";

export default function WelcomePage() {
  const router = useRouter();
  const create = useCreateWorkspace();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    const workspace = await create.mutateAsync({ name, description });
    router.replace(`/w/${workspace.slug}/workflows`);
  }

  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-8 p-6">
      <Wordmark name={runtimeEnv().productName} />
      <Card className="w-full max-w-md p-6">
        <div className="mb-5 flex items-center gap-3">
          <span className="bg-accent text-accent-foreground flex size-10 items-center justify-center rounded-xl">
            <FolderPlus className="size-5" />
          </span>
          <div>
            <h1 className="text-lg font-semibold tracking-tight">Create a workspace</h1>
            <p className="text-muted-foreground text-[13px]">
              A workspace holds workflows, credentials and the people who run them.
            </p>
          </div>
        </div>
        <form onSubmit={submit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="ws-name">Name</Label>
            <Input
              id="ws-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Operations"
              required
              autoFocus
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="ws-description">Description</Label>
            <Textarea
              id="ws-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What lives here?"
            />
          </div>
          {create.error ? <ErrorNotice message={create.error.message} /> : null}
          <Button type="submit" className="w-full" disabled={!name.trim() || create.isPending}>
            Create workspace
          </Button>
        </form>
      </Card>
    </main>
  );
}
