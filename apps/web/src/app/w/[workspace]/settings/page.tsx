"use client";

import { useParams } from "next/navigation";

import { ApiKeysPanel } from "@/components/settings/api-keys-panel";
import { AuditPanel } from "@/components/settings/audit-panel";
import { GeneralPanel } from "@/components/settings/general-panel";
import { MembersPanel } from "@/components/settings/members-panel";
import { VariablesPanel } from "@/components/settings/variables-panel";
import { ErrorNotice, Skeleton } from "@/components/ui/feedback";
import { PageBody, PageHeader } from "@/components/ui/page";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { canEdit, useWorkspace } from "@/lib/queries";

export default function SettingsPage() {
  const { workspace } = useParams<{ workspace: string }>();
  const query = useWorkspace(workspace);
  const data = query.data;
  const owner = data?.role === "owner";

  return (
    <PageBody className="max-w-4xl">
      <PageHeader
        title="Settings"
        description="Workspace defaults, shared variables, people, API keys and the audit log."
      />
      {query.error ? <ErrorNotice message={query.error.message} /> : null}
      {!data ? (
        <Skeleton className="h-64" />
      ) : (
        <Tabs defaultValue="general">
          <TabsList className="overflow-x-auto">
            <TabsTrigger value="general">General</TabsTrigger>
            <TabsTrigger value="variables">Variables</TabsTrigger>
            <TabsTrigger value="members">Members</TabsTrigger>
            {owner ? <TabsTrigger value="api-keys">API keys</TabsTrigger> : null}
            {owner ? <TabsTrigger value="audit">Audit log</TabsTrigger> : null}
          </TabsList>
          <TabsContent value="general">
            <GeneralPanel
              key={`${data.name}:${data.settings.timezone}:${data.settings.retention_days}`}
              workspace={data}
              editable={owner}
            />
          </TabsContent>
          <TabsContent value="variables">
            <VariablesPanel workspace={data.slug} editable={canEdit(data.role)} />
          </TabsContent>
          <TabsContent value="members">
            <MembersPanel workspace={data.slug} isOwner={owner} />
          </TabsContent>
          {owner ? (
            <TabsContent value="api-keys">
              <ApiKeysPanel workspace={data.slug} />
            </TabsContent>
          ) : null}
          {owner ? (
            <TabsContent value="audit">
              <AuditPanel workspace={data.slug} />
            </TabsContent>
          ) : null}
        </Tabs>
      )}
    </PageBody>
  );
}
