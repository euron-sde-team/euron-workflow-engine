"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ws } from "@/lib/api";
import type {
  ApiKey,
  ApiKeyCreated,
  AuditEvent,
  BusEvent,
  Credential,
  CredentialType,
  CronPreview,
  CursorPage,
  Dashboard,
  DashboardWindow,
  DeadLetter,
  Definition,
  DraftSaved,
  Execution,
  ExecutionDefinition,
  ExecutionSummary,
  Issue,
  LogPage,
  Me,
  Member,
  NodeSpec,
  NodeTestResult,
  NodeType,
  Page,
  Role,
  RunResult,
  StepDetail,
  SystemInfo,
  Template,
  TemplateSummary,
  User,
  Variable,
  Version,
  Workflow,
  WorkflowSummary,
  Workspace,
  WorkspaceSettings,
} from "@/lib/types";

export const qk = {
  system: ["system"] as const,
  me: ["me"] as const,
  nodeTypes: ["node-types"] as const,
  credentialTypes: ["credential-types"] as const,
  templates: ["templates"] as const,
  template: (slug: string) => ["template", slug] as const,
  workspace: (w: string) => ["workspace", w] as const,
  dashboard: (w: string, window: DashboardWindow) => ["dashboard", w, window] as const,
  workflows: (w: string, filters: WorkflowFilters) => ["workflows", w, filters] as const,
  workflowsAll: (w: string) => ["workflows", w] as const,
  workflow: (w: string, id: string) => ["workflow", w, id] as const,
  versions: (w: string, id: string) => ["versions", w, id] as const,
  executions: (w: string, filters: ExecutionFilters) => ["executions", w, filters] as const,
  executionsAll: (w: string) => ["executions", w] as const,
  execution: (w: string, id: string) => ["execution", w, id] as const,
  step: (w: string, executionId: string, stepId: string) => ["step", w, executionId, stepId] as const,
  logs: (w: string, executionId: string) => ["logs", w, executionId] as const,
  deadLetters: (w: string, status: string) => ["dead-letters", w, status] as const,
  credentials: (w: string) => ["credentials", w] as const,
  variables: (w: string) => ["variables", w] as const,
  events: (w: string, name: string) => ["events", w, name] as const,
  members: (w: string) => ["members", w] as const,
  apiKeys: (w: string) => ["api-keys", w] as const,
  audit: (w: string) => ["audit", w] as const,
};

export type WorkflowFilters = { search?: string; tag?: string; active?: string };
export type ExecutionFilters = { status?: string; workflow_id?: string; trigger?: string; mode?: string };

const ACTIVE: ReadonlySet<string> = new Set(["queued", "running", "waiting"]);

/* Session and workspace ---------------------------------------------------------------------- */

export function useSystemInfo() {
  return useQuery({ queryKey: qk.system, queryFn: () => api<SystemInfo>("/api/v1/system/info"), staleTime: 300_000 });
}

export function useMe() {
  return useQuery({ queryKey: qk.me, queryFn: () => api<Me>("/api/v1/auth/me"), retry: false });
}

export function useLogin() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { email: string; password: string }) =>
      api<{ user: User }>("/api/v1/auth/login", { method: "POST", json: body }),
    onSuccess: () => client.invalidateQueries({ queryKey: qk.me }),
  });
}

export function useSignup() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { email: string; name: string; password: string }) =>
      api<{ user: User }>("/api/v1/auth/signup", { method: "POST", json: body }),
    onSuccess: () => client.invalidateQueries({ queryKey: qk.me }),
  });
}

export function useLogout() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api<void>("/api/v1/auth/logout", { method: "POST" }),
    onSettled: () => client.clear(),
  });
}

export function useWorkspace(workspace: string) {
  return useQuery({ queryKey: qk.workspace(workspace), queryFn: () => api<Workspace>(ws(workspace)) });
}

export function useCreateWorkspace() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; description?: string }) =>
      api<Workspace>("/api/v1/workspaces", { method: "POST", json: body }),
    onSuccess: () => client.invalidateQueries({ queryKey: qk.me }),
  });
}

export function useUpdateWorkspace(workspace: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { name?: string; description?: string; settings?: WorkspaceSettings }) =>
      api<Workspace>(ws(workspace), { method: "PATCH", json: body }),
    onSuccess: (updated) => {
      client.setQueryData(qk.workspace(workspace), updated);
      void client.invalidateQueries({ queryKey: qk.me });
    },
  });
}

/** The signed-in user's summary of a workspace (including their role), from the session cache. */
export function useCurrentWorkspace(workspace: string) {
  const me = useMe();
  return me.data?.workspaces.find((w) => w.slug === workspace || w.id === workspace);
}

export function canEdit(role: Role | undefined): boolean {
  return role === "owner" || role === "editor";
}

/* Catalog ---------------------------------------------------------------------------------------- */

export function useNodeTypes() {
  return useQuery({ queryKey: qk.nodeTypes, queryFn: () => api<NodeType[]>("/api/v1/node-types"), staleTime: Infinity });
}

export function useCredentialTypes() {
  return useQuery({
    queryKey: qk.credentialTypes,
    queryFn: () => api<CredentialType[]>("/api/v1/credential-types"),
    staleTime: Infinity,
  });
}

export function useTemplates() {
  return useQuery({ queryKey: qk.templates, queryFn: () => api<TemplateSummary[]>("/api/v1/templates"), staleTime: 300_000 });
}

export function useTemplate(slug: string | null) {
  return useQuery({
    queryKey: qk.template(slug ?? "none"),
    queryFn: () => api<Template>(`/api/v1/templates/${slug}`),
    enabled: Boolean(slug),
    staleTime: 300_000,
  });
}

export function useCronPreview() {
  return useMutation({
    mutationFn: (body: { expression: string; timezone: string; count?: number }) =>
      api<CronPreview>("/api/v1/tools/cron-preview", { method: "POST", json: body }),
  });
}

/* Dashboard ------------------------------------------------------------------------------------- */

export function useDashboard(workspace: string, window: DashboardWindow) {
  return useQuery({
    queryKey: qk.dashboard(workspace, window),
    queryFn: () => api<Dashboard>(`${ws(workspace)}/dashboard?window=${window}`),
    refetchInterval: 15_000,
  });
}

/* Workflows ------------------------------------------------------------------------------------ */

export function useWorkflows(workspace: string, filters: WorkflowFilters, limit = 50) {
  const params = new URLSearchParams({ limit: String(limit) });
  for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
  return useQuery({
    queryKey: qk.workflows(workspace, { ...filters }),
    queryFn: () => api<Page<WorkflowSummary>>(`${ws(workspace)}/workflows?${params}`),
  });
}

export function useWorkflow(workspace: string, id: string) {
  return useQuery({
    queryKey: qk.workflow(workspace, id),
    queryFn: () => api<Workflow>(`${ws(workspace)}/workflows/${id}`),
  });
}

export function useCreateWorkflow(workspace: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; description?: string; tags?: string[]; template?: string; definition?: Definition }) =>
      api<Workflow>(`${ws(workspace)}/workflows`, { method: "POST", json: body }),
    onSuccess: () => client.invalidateQueries({ queryKey: qk.workflowsAll(workspace) }),
  });
}

export function useImportWorkflow(workspace: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (document: unknown) =>
      api<{ workflow: Workflow; unresolved_credentials: { name: string; type: string }[] }>(
        `${ws(workspace)}/workflows/import`,
        { method: "POST", json: document },
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: qk.workflowsAll(workspace) }),
  });
}

export function useSaveDraft(workspace: string, id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { definition: Definition; revision: number }) =>
      api<DraftSaved>(`${ws(workspace)}/workflows/${id}/draft`, { method: "PUT", json: body }),
    onSuccess: () => client.invalidateQueries({ queryKey: qk.workflowsAll(workspace) }),
  });
}

export function useValidate(workspace: string, id: string) {
  return useMutation({
    mutationFn: (definition: Definition) =>
      api<Issue[]>(`${ws(workspace)}/workflows/${id}/validate`, { method: "POST", json: { definition } }),
  });
}

export function useWorkflowActions(workspace: string, id: string) {
  const client = useQueryClient();
  const refresh = (workflow?: Workflow) => {
    if (workflow) client.setQueryData(qk.workflow(workspace, id), workflow);
    void client.invalidateQueries({ queryKey: qk.workflowsAll(workspace) });
    void client.invalidateQueries({ queryKey: qk.versions(workspace, id) });
  };
  const base = `${ws(workspace)}/workflows/${id}`;
  return {
    update: useMutation({
      mutationFn: (body: {
        name?: string;
        description?: string;
        tags?: string[];
        concurrency_limit?: number | null;
        clear_concurrency_limit?: boolean;
        timeout_s?: number;
      }) => api<Workflow>(base, { method: "PATCH", json: body }),
      onSuccess: refresh,
    }),
    publish: useMutation({
      mutationFn: (body: { note: string; activate: boolean }) =>
        api<Workflow>(`${base}/publish`, { method: "POST", json: body }),
      onSuccess: refresh,
    }),
    activate: useMutation({
      mutationFn: () => api<Workflow>(`${base}/activate`, { method: "POST" }),
      onSuccess: refresh,
    }),
    deactivate: useMutation({
      mutationFn: () => api<Workflow>(`${base}/deactivate`, { method: "POST" }),
      onSuccess: refresh,
    }),
    restore: useMutation({
      mutationFn: (number: number) => api<Workflow>(`${base}/versions/${number}/restore`, { method: "POST" }),
      onSuccess: refresh,
    }),
    duplicate: useMutation({
      mutationFn: () => api<Workflow>(`${base}/duplicate`, { method: "POST" }),
      onSuccess: () => client.invalidateQueries({ queryKey: qk.workflowsAll(workspace) }),
    }),
    remove: useMutation({
      mutationFn: () => api<void>(base, { method: "DELETE" }),
      onSuccess: () => client.invalidateQueries({ queryKey: qk.workflowsAll(workspace) }),
    }),
    run: useMutation({
      mutationFn: (body: { payload?: unknown; use_draft: boolean; trigger_node?: string }) =>
        api<RunResult>(`${base}/run`, { method: "POST", json: body }),
      onSuccess: () => client.invalidateQueries({ queryKey: qk.executionsAll(workspace) }),
    }),
  };
}

export function useVersions(workspace: string, id: string, enabled = true) {
  return useQuery({
    queryKey: qk.versions(workspace, id),
    queryFn: () => api<Version[]>(`${ws(workspace)}/workflows/${id}/versions`),
    enabled,
  });
}

export async function exportWorkflow(workspace: string, id: string): Promise<unknown> {
  return api<unknown>(`${ws(workspace)}/workflows/${id}/export`);
}

export function useTestNode(workspace: string) {
  return useMutation({
    mutationFn: (body: {
      node: Pick<NodeSpec, "type" | "config"> & Partial<NodeSpec>;
      input?: unknown;
      trigger?: unknown;
      steps?: Record<string, unknown>;
      vars?: Record<string, unknown>;
    }) => api<NodeTestResult>(`${ws(workspace)}/nodes/test`, { method: "POST", json: body }),
  });
}

/* Executions ------------------------------------------------------------------------------------ */

export function useExecutions(workspace: string, filters: ExecutionFilters, cursor: string | null, limit = 25) {
  const params = new URLSearchParams({ limit: String(limit) });
  for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
  if (cursor) params.set("cursor", cursor);
  return useQuery({
    queryKey: [...qk.executions(workspace, { ...filters }), cursor ?? "first"],
    queryFn: () => api<CursorPage<ExecutionSummary>>(`${ws(workspace)}/executions?${params}`),
    // Keep the list live while anything on the page is still moving.
    refetchInterval: (query) => (query.state.data?.items.some((e) => ACTIVE.has(e.status)) ? 2000 : 10_000),
  });
}

export function useExecution(workspace: string, id: string | null) {
  return useQuery({
    queryKey: qk.execution(workspace, id ?? "none"),
    queryFn: () => api<Execution>(`${ws(workspace)}/executions/${id}`),
    enabled: Boolean(id),
    refetchInterval: (query) => (query.state.data && ACTIVE.has(query.state.data.status) ? 1000 : false),
  });
}

/** The definition an execution ran never changes, so it is fetched once. */
export function useExecutionDefinition(workspace: string, id: string) {
  return useQuery({
    queryKey: ["execution-definition", workspace, id],
    queryFn: () => api<ExecutionDefinition>(`${ws(workspace)}/executions/${id}/definition`),
    staleTime: Infinity,
  });
}

export function useStep(workspace: string, executionId: string, stepId: string | null, live = false) {
  return useQuery({
    queryKey: qk.step(workspace, executionId, stepId ?? "none"),
    queryFn: () => api<StepDetail>(`${ws(workspace)}/executions/${executionId}/steps/${stepId}`),
    enabled: Boolean(stepId),
    refetchInterval: live ? 1500 : false,
  });
}

export function useLogs(workspace: string, executionId: string, live = false) {
  return useQuery({
    queryKey: qk.logs(workspace, executionId),
    queryFn: () => api<LogPage>(`${ws(workspace)}/executions/${executionId}/logs?limit=500`),
    refetchInterval: live ? 1500 : false,
  });
}

export function useExecutionActions(workspace: string, id: string) {
  const client = useQueryClient();
  const refresh = () => {
    void client.invalidateQueries({ queryKey: qk.execution(workspace, id) });
    void client.invalidateQueries({ queryKey: qk.executionsAll(workspace) });
    void client.invalidateQueries({ queryKey: ["dead-letters", workspace] });
  };
  const base = `${ws(workspace)}/executions/${id}`;
  return {
    cancel: useMutation({ mutationFn: () => api<ExecutionSummary>(`${base}/cancel`, { method: "POST" }), onSuccess: refresh }),
    resume: useMutation({ mutationFn: () => api<ExecutionSummary>(`${base}/resume`, { method: "POST" }), onSuccess: refresh }),
    retry: useMutation({ mutationFn: () => api<RunResult>(`${base}/retry`, { method: "POST" }), onSuccess: refresh }),
  };
}

/* Dead letters ---------------------------------------------------------------------------------- */

export function useDeadLetters(workspace: string, status: string) {
  return useQuery({
    queryKey: qk.deadLetters(workspace, status),
    queryFn: () => api<CursorPage<DeadLetter>>(`${ws(workspace)}/dead-letters?status=${status}&limit=100`),
  });
}

export function useDeadLetterActions(workspace: string) {
  const client = useQueryClient();
  const refresh = () => {
    void client.invalidateQueries({ queryKey: ["dead-letters", workspace] });
    void client.invalidateQueries({ queryKey: qk.executionsAll(workspace) });
  };
  return {
    retry: useMutation({
      mutationFn: (id: string) => api<ExecutionSummary>(`${ws(workspace)}/dead-letters/${id}/retry`, { method: "POST" }),
      onSuccess: refresh,
    }),
    discard: useMutation({
      mutationFn: (id: string) => api<DeadLetter>(`${ws(workspace)}/dead-letters/${id}/discard`, { method: "POST" }),
      onSuccess: refresh,
    }),
  };
}

/* Credentials and variables ------------------------------------------------------------------------ */

export function useCredentials(workspace: string) {
  return useQuery({ queryKey: qk.credentials(workspace), queryFn: () => api<Credential[]>(`${ws(workspace)}/credentials`) });
}

export function useCredentialActions(workspace: string) {
  const client = useQueryClient();
  const refresh = () => client.invalidateQueries({ queryKey: qk.credentials(workspace) });
  return {
    create: useMutation({
      mutationFn: (body: { name: string; type: string; description: string; data: Record<string, unknown> }) =>
        api<Credential>(`${ws(workspace)}/credentials`, { method: "POST", json: body }),
      onSuccess: refresh,
    }),
    update: useMutation({
      mutationFn: ({ id, ...body }: { id: string; name?: string; description?: string; data?: Record<string, unknown> }) =>
        api<Credential>(`${ws(workspace)}/credentials/${id}`, { method: "PATCH", json: body }),
      onSuccess: refresh,
    }),
    remove: useMutation({
      mutationFn: (id: string) => api<void>(`${ws(workspace)}/credentials/${id}`, { method: "DELETE" }),
      onSuccess: refresh,
    }),
  };
}

export function useVariables(workspace: string) {
  return useQuery({ queryKey: qk.variables(workspace), queryFn: () => api<Variable[]>(`${ws(workspace)}/variables`) });
}

export function useVariableActions(workspace: string) {
  const client = useQueryClient();
  const refresh = () => client.invalidateQueries({ queryKey: qk.variables(workspace) });
  return {
    put: useMutation({
      mutationFn: ({ key, ...body }: { key: string; value: string; description: string }) =>
        api<Variable>(`${ws(workspace)}/variables/${key}`, { method: "PUT", json: body }),
      onSuccess: refresh,
    }),
    remove: useMutation({
      mutationFn: (key: string) => api<void>(`${ws(workspace)}/variables/${key}`, { method: "DELETE" }),
      onSuccess: refresh,
    }),
  };
}

/* Events ------------------------------------------------------------------------------------------- */

export function useEvents(workspace: string, name: string) {
  const params = new URLSearchParams({ limit: "50" });
  if (name) params.set("name", name);
  return useQuery({
    queryKey: qk.events(workspace, name),
    queryFn: () => api<CursorPage<BusEvent>>(`${ws(workspace)}/events?${params}`),
    refetchInterval: 10_000,
  });
}

export function usePublishEvent(workspace: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; payload: unknown }) =>
      api<{ event_id: string; matched: number; executions: string[] }>(`${ws(workspace)}/events`, {
        method: "POST",
        json: body,
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["events", workspace] });
      void client.invalidateQueries({ queryKey: qk.executionsAll(workspace) });
    },
  });
}

/* People, keys and audit ------------------------------------------------------------------------- */

export function useMembers(workspace: string) {
  return useQuery({ queryKey: qk.members(workspace), queryFn: () => api<Member[]>(`${ws(workspace)}/members`) });
}

export function useMemberActions(workspace: string) {
  const client = useQueryClient();
  const refresh = () => client.invalidateQueries({ queryKey: qk.members(workspace) });
  return {
    add: useMutation({
      mutationFn: (body: { email: string; name?: string; role: Role }) =>
        api<{ member: Member; temporary_password: string | null }>(`${ws(workspace)}/members`, {
          method: "POST",
          json: body,
        }),
      onSuccess: refresh,
    }),
    changeRole: useMutation({
      mutationFn: ({ userId, role }: { userId: string; role: Role }) =>
        api<Member>(`${ws(workspace)}/members/${userId}`, { method: "PATCH", json: { role } }),
      onSuccess: refresh,
    }),
    remove: useMutation({
      mutationFn: (userId: string) => api<void>(`${ws(workspace)}/members/${userId}`, { method: "DELETE" }),
      onSuccess: refresh,
    }),
  };
}

export function useApiKeys(workspace: string, enabled = true) {
  return useQuery({ queryKey: qk.apiKeys(workspace), queryFn: () => api<ApiKey[]>(`${ws(workspace)}/api-keys`), enabled });
}

export function useApiKeyActions(workspace: string) {
  const client = useQueryClient();
  const refresh = () => client.invalidateQueries({ queryKey: qk.apiKeys(workspace) });
  return {
    create: useMutation({
      mutationFn: (body: { name: string; role: "viewer" | "editor"; expires_in_days: number | null }) =>
        api<ApiKeyCreated>(`${ws(workspace)}/api-keys`, { method: "POST", json: body }),
      onSuccess: refresh,
    }),
    revoke: useMutation({
      mutationFn: (id: string) => api<void>(`${ws(workspace)}/api-keys/${id}`, { method: "DELETE" }),
      onSuccess: refresh,
    }),
  };
}

export function useAudit(workspace: string, enabled = true) {
  return useQuery({
    queryKey: qk.audit(workspace),
    queryFn: () => api<CursorPage<AuditEvent>>(`${ws(workspace)}/audit?limit=100`),
    enabled,
  });
}
