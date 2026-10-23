"use client";

import {
  Check,
  CircleAlert,
  KeyRound,
  LayoutTemplate,
  Variable as VariableIcon,
} from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import { toast } from "sonner";

import { NodeIcon } from "@/components/node-icon";
import { TriggerLabel } from "@/components/trigger-badge";
import { GraphPreview } from "@/components/workflows/graph-preview";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { EmptyState, ErrorNotice, Skeleton, Spinner } from "@/components/ui/feedback";
import { PageBody, PageHeader } from "@/components/ui/page";
import { cn } from "@/lib/cn";
import {
  canEdit,
  useCreateWorkflow,
  useCredentials,
  useCurrentWorkspace,
  useNodeTypes,
  useTemplate,
  useTemplates,
  useVariables,
} from "@/lib/queries";
import type { NodeType, TemplateSummary } from "@/lib/types";

function NeedRow({
  ok,
  icon,
  label,
  detail,
}: {
  ok: boolean | undefined;
  icon: ReactNode;
  label: string;
  detail: string;
}) {
  return (
    <li className="flex items-center gap-2.5 py-1.5 text-[13px]">
      <span className="text-muted-foreground [&_svg]:size-4">{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="font-medium">{label}</span>{" "}
        <span className="text-muted-foreground">{detail}</span>
      </span>
      {ok ? (
        <Badge tone="success">
          <Check /> In this workspace
        </Badge>
      ) : (
        <Badge tone="warning">
          <CircleAlert /> Add it
        </Badge>
      )}
    </li>
  );
}

function Needs({ template, workspace }: { template: TemplateSummary; workspace: string }) {
  const credentials = useCredentials(workspace);
  const variables = useVariables(workspace);
  const haveCredential = (name: string, type: string) =>
    credentials.data?.some((c) => c.type === type && c.name.toLowerCase() === name.toLowerCase());
  const haveVariable = (key: string) => variables.data?.some((v) => v.key === key);
  if (!template.credentials.length && !template.variables.length) {
    return (
      <p className="text-muted-foreground text-[13px]">It needs no credentials or variables.</p>
    );
  }
  return (
    <ul className="divide-border divide-y">
      {template.credentials.map((c) => (
        <NeedRow
          key={`${c.type}:${c.name}`}
          ok={haveCredential(c.name, c.type)}
          icon={<KeyRound />}
          label={c.name}
          detail={c.type.replaceAll("_", " ")}
        />
      ))}
      {template.variables.map((v) => (
        <NeedRow
          key={v.key}
          ok={haveVariable(v.key)}
          icon={<VariableIcon />}
          label={v.key}
          detail={`for example ${v.example}`}
        />
      ))}
    </ul>
  );
}

function PreviewBody({
  slug,
  workspace,
  types,
  editable,
}: {
  slug: string;
  workspace: string;
  types: NodeType[];
  editable: boolean;
}) {
  const router = useRouter();
  const template = useTemplate(slug);
  const create = useCreateWorkflow(workspace);
  if (!template.data)
    return template.error ? (
      <ErrorNotice message={template.error.message} />
    ) : (
      <Skeleton className="h-80" />
    );
  const data = template.data;

  async function use() {
    const workflow = await create.mutateAsync({ name: data.name, template: data.slug });
    toast.success("Template copied into a new draft");
    router.push(`/w/${workspace}/workflows/${workflow.id}`);
  }

  return (
    <div className="space-y-4">
      <p className="text-muted-foreground text-[13px] leading-relaxed">{data.description}</p>
      <GraphPreview definition={data.definition} types={types} />
      <div>
        <p className="text-subtle mb-1 text-[12px] font-medium tracking-wide uppercase">
          What it needs
        </p>
        <Needs template={data} workspace={workspace} />
      </div>
      {create.error ? <ErrorNotice message={create.error.message} /> : null}
      {editable ? (
        <DialogFooter>
          <Button onClick={() => void use()} disabled={create.isPending} data-testid="use-template">
            {create.isPending ? (
              <Spinner className="text-primary-foreground" />
            ) : (
              <LayoutTemplate />
            )}
            Use this template
          </Button>
        </DialogFooter>
      ) : null}
    </div>
  );
}

export default function TemplatesPage() {
  const { workspace } = useParams<{ workspace: string }>();
  const current = useCurrentWorkspace(workspace);
  const templates = useTemplates();
  const types = useNodeTypes();
  const [category, setCategory] = useState("All");
  const [preview, setPreview] = useState<string | null>(null);
  const typeMap = new Map((types.data ?? []).map((t) => [t.type, t]));
  const categories = ["All", ...new Set((templates.data ?? []).map((t) => t.category))];
  const shown = (templates.data ?? []).filter((t) => category === "All" || t.category === category);
  const previewing = templates.data?.find((t) => t.slug === preview);

  return (
    <PageBody>
      <PageHeader
        title="Templates"
        description="Working automations to start from. Each one says which credentials and variables it expects."
      />
      {templates.error ? <ErrorNotice message={templates.error.message} /> : null}
      {!templates.data ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <Skeleton key={i} className="h-56" />
          ))}
        </div>
      ) : templates.data.length === 0 ? (
        <Card>
          <EmptyState icon={<LayoutTemplate />} title="No templates" />
        </Card>
      ) : (
        <>
          <div className="mb-5 flex flex-wrap gap-1.5" role="tablist" aria-label="Categories">
            {categories.map((name) => (
              <button
                key={name}
                type="button"
                role="tab"
                aria-selected={category === name}
                onClick={() => setCategory(name)}
                className={cn(
                  "rounded-full border px-3 py-1 text-[12.5px] font-medium transition-colors",
                  category === name
                    ? "border-primary bg-accent text-accent-foreground"
                    : "border-border text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
              >
                {name}
              </button>
            ))}
          </div>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {shown.map((template) => (
              <Card
                key={template.slug}
                className="flex flex-col p-5"
                data-testid={`template-${template.slug}`}
              >
                <div className="flex items-center justify-between gap-2">
                  <Badge tone="primary">{template.category}</Badge>
                  <span className="flex gap-2">
                    {template.trigger_kinds.map((kind) => (
                      <TriggerLabel key={kind} kind={kind} />
                    ))}
                  </span>
                </div>
                <h2 className="mt-3 text-[15px] font-semibold tracking-tight">{template.name}</h2>
                <p className="text-muted-foreground mt-1 flex-1 text-[13px] leading-relaxed">
                  {template.summary}
                </p>
                <div className="mt-4 flex items-center gap-1.5" aria-label="Node types">
                  {template.node_types
                    .filter((t) => !t.startsWith("trigger."))
                    .slice(0, 7)
                    .map((type) => {
                      const nodeType = typeMap.get(type);
                      return (
                        <span key={type} title={nodeType?.name ?? type}>
                          <NodeIcon
                            icon={nodeType?.icon ?? "blocks"}
                            category={nodeType?.category}
                            className="size-7"
                          />
                        </span>
                      );
                    })}
                </div>
                <div className="border-border mt-4 flex items-center justify-between gap-2 border-t pt-3">
                  <span className="text-muted-foreground text-[12px]">
                    {template.credentials.length} credential
                    {template.credentials.length === 1 ? "" : "s"}, {template.variables.length}{" "}
                    variable{template.variables.length === 1 ? "" : "s"}
                  </span>
                  <Button size="sm" variant="secondary" onClick={() => setPreview(template.slug)}>
                    Preview
                  </Button>
                </div>
              </Card>
            ))}
          </div>
        </>
      )}
      <Dialog open={Boolean(preview)} onOpenChange={(open) => !open && setPreview(null)}>
        {previewing ? (
          <DialogContent
            title={previewing.name}
            description={previewing.summary}
            className="w-[min(94vw,52rem)]"
          >
            <PreviewBody
              slug={previewing.slug}
              workspace={workspace}
              types={types.data ?? []}
              editable={canEdit(current?.role)}
            />
          </DialogContent>
        ) : null}
      </Dialog>
    </PageBody>
  );
}
