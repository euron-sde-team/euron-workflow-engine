"use client";

import { UserPlus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { CopyField } from "@/components/settings/copy-field";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { ErrorNotice, Skeleton } from "@/components/ui/feedback";
import { FieldHint, Input, Label, NativeSelect } from "@/components/ui/input";
import { formatRelative, initials } from "@/lib/format";
import { useMe, useMemberActions, useMembers } from "@/lib/queries";
import type { Role } from "@/lib/types";

const ROLE_HELP: Record<Role, string> = {
  owner: "Everything, including members, workspace settings and API keys",
  editor: "Build, publish and run workflows; manage credentials, variables and dead letters",
  viewer: "See workflows, executions and the dashboard",
};

export function MembersPanel({ workspace, isOwner }: { workspace: string; isOwner: boolean }) {
  const members = useMembers(workspace);
  const me = useMe();
  const actions = useMemberActions(workspace);
  const [adding, setAdding] = useState(false);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<Role>("viewer");
  const [password, setPassword] = useState<string | null>(null);

  async function add(event: FormEvent) {
    event.preventDefault();
    const result = await actions.add.mutateAsync({ email, name: name || undefined, role });
    toast.success(`${result.member.name} added as ${result.member.role}`);
    if (result.temporary_password) setPassword(result.temporary_password);
    else setAdding(false);
    setEmail("");
    setName("");
  }

  return (
    <Card>
      <div className="border-border flex items-center justify-between gap-3 border-b px-5 py-3.5">
        <p className="text-muted-foreground text-[13px]">
          {members.data?.length ?? 0} people can use this workspace.
        </p>
        {isOwner ? (
          <Button size="sm" onClick={() => setAdding(true)}>
            <UserPlus /> Add member
          </Button>
        ) : null}
      </div>
      {members.isLoading ? (
        <div className="space-y-2 p-5">
          <Skeleton className="h-10" />
          <Skeleton className="h-10" />
        </div>
      ) : (
        <ul className="divide-border divide-y">
          {(members.data ?? []).map((member) => (
            <li key={member.user_id} className="flex flex-wrap items-center gap-3 px-5 py-3">
              <span className="bg-muted ring-border flex size-8 items-center justify-center rounded-full text-[11px] font-semibold ring-1">
                {initials(member.name)}
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-[13.5px] font-medium">
                  {member.name}{" "}
                  {member.user_id === me.data?.user.id ? (
                    <span className="text-muted-foreground">(you)</span>
                  ) : null}
                </p>
                <p className="text-muted-foreground truncate text-xs">
                  {member.email} &middot; joined {formatRelative(member.joined_at)}
                </p>
              </div>
              {isOwner ? (
                <>
                  <NativeSelect
                    value={member.role}
                    className="w-32"
                    aria-label={`Role for ${member.name}`}
                    onChange={async (e) => {
                      try {
                        await actions.changeRole.mutateAsync({
                          userId: member.user_id,
                          role: e.target.value as Role,
                        });
                        toast.success("Role updated");
                      } catch (error) {
                        toast.error((error as Error).message);
                      }
                    }}
                  >
                    <option value="owner">Owner</option>
                    <option value="editor">Editor</option>
                    <option value="viewer">Viewer</option>
                  </NativeSelect>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={async () => {
                      try {
                        await actions.remove.mutateAsync(member.user_id);
                        toast.success(`${member.name} removed`);
                      } catch (error) {
                        toast.error((error as Error).message);
                      }
                    }}
                  >
                    Remove
                  </Button>
                </>
              ) : (
                <span className="text-muted-foreground text-[13px] capitalize">{member.role}</span>
              )}
            </li>
          ))}
        </ul>
      )}
      <Dialog
        open={adding}
        onOpenChange={(open) => {
          setAdding(open);
          if (!open) setPassword(null);
        }}
      >
        <DialogContent
          title={password ? "Share these sign-in details" : "Add a member"}
          description={
            password
              ? "This temporary password is shown once. Ask them to change it after signing in."
              : "If they do not have an account yet, one is created with a temporary password."
          }
        >
          {password ? (
            <div className="space-y-3">
              <CopyField value={password} label="Temporary password" />
              <DialogFooter>
                <Button
                  onClick={() => {
                    setAdding(false);
                    setPassword(null);
                  }}
                >
                  Done
                </Button>
              </DialogFooter>
            </div>
          ) : (
            <form onSubmit={add} className="space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="member-email">Email</Label>
                <Input
                  id="member-email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  autoFocus
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="member-name">Name</Label>
                <Input
                  id="member-name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Optional"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="member-role">Role</Label>
                <NativeSelect
                  id="member-role"
                  value={role}
                  onChange={(e) => setRole(e.target.value as Role)}
                >
                  <option value="viewer">Viewer</option>
                  <option value="editor">Editor</option>
                  <option value="owner">Owner</option>
                </NativeSelect>
                <FieldHint>{ROLE_HELP[role]}</FieldHint>
              </div>
              {actions.add.error ? <ErrorNotice message={actions.add.error.message} /> : null}
              <DialogFooter>
                <Button type="button" variant="secondary" onClick={() => setAdding(false)}>
                  Cancel
                </Button>
                <Button type="submit" disabled={!email || actions.add.isPending}>
                  Add member
                </Button>
              </DialogFooter>
            </form>
          )}
        </DialogContent>
      </Dialog>
    </Card>
  );
}
