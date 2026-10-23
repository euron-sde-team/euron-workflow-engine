/** API shapes, mirroring apps/api/src/workflow_engine/schemas. */

export type Role = "owner" | "editor" | "viewer";
export type ExecutionStatus = "queued" | "running" | "waiting" | "succeeded" | "failed" | "cancelled";
export type StepStatus = "queued" | "running" | "waiting" | "succeeded" | "failed" | "skipped" | "cancelled";
export type ExecutionMode = "production" | "manual" | "test";
export type TriggerKind = "manual" | "webhook" | "cron" | "interval" | "event" | "retry";

export type Page<T> = { items: T[]; total: number; limit: number; offset: number };
export type CursorPage<T> = { items: T[]; next_cursor: string | null };

export type User = {
  id: string;
  email: string;
  name: string;
  is_admin: boolean;
  created_at: string;
  last_login_at: string | null;
};

export type WorkspaceSummary = {
  id: string;
  slug: string;
  name: string;
  role: Role;
  workflow_count: number;
  active_workflow_count: number;
  member_count: number;
};

export type Me = { user: User; workspaces: WorkspaceSummary[] };

export type WorkspaceSettings = {
  timezone: string;
  retention_days: number;
  default_timeout_s: number;
};

export type Workspace = {
  id: string;
  slug: string;
  name: string;
  description: string;
  settings: WorkspaceSettings;
  role: Role;
  created_at: string;
};

export type Member = { user_id: string; email: string; name: string; role: Role; joined_at: string };

export type SystemInfo = {
  product_name: string;
  version: string;
  hooks_base_url: string;
  allow_signup: boolean;
  needs_setup: boolean;
  vault_provider: string;
  mail_from: string;
  workflow_data_bucket: string | null;
  sqs_allowed_queues: string[];
  max_payload_kb: number;
  webhook_max_body_kb: number;
};

/* Workflow definitions ------------------------------------------------------------------ */

export type RetryPolicy = {
  max_attempts: number;
  initial_delay_ms: number;
  max_delay_ms: number;
  multiplier: number;
  jitter: boolean;
};

export type NodeSpec = {
  id: string;
  type: string;
  name: string;
  config: Record<string, unknown>;
  position: { x: number; y: number };
  retry?: RetryPolicy | null;
  timeout_s?: number | null;
  on_error?: "fail" | "continue";
  disabled?: boolean;
  notes?: string;
};

export type EdgeSpec = {
  id: string;
  source: string;
  source_port: string;
  target: string;
  target_port: string;
};

export type Definition = { schema_version: 1; nodes: NodeSpec[]; edges: EdgeSpec[] };

export type Issue = {
  severity: "error" | "warning";
  code: string;
  message: string;
  node_id: string | null;
  field: string | null;
  edge_id: string | null;
};

export type TriggerInfo = {
  node_id: string;
  kind: string;
  summary: string;
  next_fire_at: string | null;
  url: string | null;
  method: string | null;
};

export type WorkflowSummary = {
  id: string;
  name: string;
  description: string;
  tags: string[];
  active: boolean;
  published_version: number | null;
  has_unpublished_changes: boolean;
  trigger_kinds: string[];
  concurrency_limit: number | null;
  timeout_s: number;
  template_slug: string | null;
  created_at: string;
  updated_at: string;
  last_execution: { id: string; status: ExecutionStatus; created_at: string } | null;
  stats_7d: { total: number; succeeded: number; failed: number; success_rate: number | null };
  next_run_at: string | null;
};

export type Workflow = WorkflowSummary & {
  draft: Definition;
  draft_revision: number;
  draft_updated_at: string;
  triggers: TriggerInfo[];
  issues: Issue[];
};

export type DraftSaved = { revision: number; updated_at: string; issues: Issue[] };

export type Version = {
  id: string;
  number: number;
  note: string;
  checksum: string;
  node_count: number;
  created_at: string;
  is_current: boolean;
};

export type RunResult = { execution_id: string; status: ExecutionStatus; duplicate: boolean };

/* Catalog --------------------------------------------------------------------------------- */

export type JsonSchema = {
  type?: string | string[];
  title?: string;
  description?: string;
  default?: unknown;
  enum?: unknown[];
  const?: unknown;
  properties?: Record<string, JsonSchema>;
  required?: string[];
  items?: JsonSchema;
  anyOf?: JsonSchema[];
  $ref?: string;
  $defs?: Record<string, JsonSchema>;
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number;
  minLength?: number;
  maxLength?: number;
  pattern?: string;
  format?: string;
  "x-template"?: boolean;
  "x-widget"?: string;
  "x-credential-types"?: string[];
  "x-secret"?: boolean;
};

export type NodeType = {
  type: string;
  name: string;
  category: "trigger" | "core" | "flow" | "integration";
  description: string;
  icon: string;
  is_trigger: boolean;
  inputs: string[];
  ports: string[];
  port_labels: Record<string, string>;
  dynamic_ports: boolean;
  side_effects: boolean;
  default_retry: RetryPolicy;
  default_timeout_s: number;
  template_fields: string[];
  credential_fields: Record<string, string[]>;
  config_schema: JsonSchema;
  sample_output: unknown;
};

export type CredentialType = {
  type: string;
  name: string;
  description: string;
  icon: string;
  secret_fields: string[];
  json_schema: JsonSchema;
};

export type TemplateSummary = {
  slug: string;
  name: string;
  summary: string;
  description: string;
  category: string;
  tags: string[];
  node_types: string[];
  trigger_kinds: string[];
  credentials: { name: string; type: string }[];
  variables: { key: string; example: string; description?: string }[];
};

export type Template = TemplateSummary & { definition: Definition };

export type CronPreview = { valid: boolean; description: string | null; next: string[]; error: string | null };

/* Executions ------------------------------------------------------------------------------ */

export type ExecutionError = { code: string; message: string; node_id?: string | null; step_id?: string | null };

export type ExecutionSummary = {
  id: string;
  workflow_id: string;
  workflow_name: string;
  version_id: string;
  status: ExecutionStatus;
  mode: ExecutionMode;
  trigger_kind: TriggerKind;
  trigger_node_id: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  error: ExecutionError | null;
  resume_count: number;
  retry_of_id: string | null;
};

export type StepSummary = {
  id: string;
  node_id: string;
  node_type: string;
  node_name: string;
  run_index: number;
  scope: string;
  status: StepStatus;
  attempt: number;
  max_attempts: number;
  ports: string[];
  error: (ExecutionError & { retryable?: boolean; attempt?: number; details?: unknown }) | null;
  available_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
};

export type StepDetail = StepSummary & { input: unknown; output: unknown; state: Record<string, unknown> };

export type Execution = ExecutionSummary & {
  trigger_payload: unknown;
  output: unknown;
  variables: Record<string, unknown>;
  version_number: number | null;
  steps: StepSummary[];
  steps_truncated: boolean;
};

export type ExecutionDefinition = { version_id: string; version_number: number | null; definition: Definition };

export type LogLine = {
  id: number;
  step_id: string | null;
  level: "debug" | "info" | "warn" | "error";
  message: string;
  data: Record<string, unknown>;
  created_at: string;
};

export type LogPage = { items: LogLine[]; next_after: number | null };

export type DeadLetter = {
  id: string;
  workflow_id: string;
  workflow_name: string;
  execution_id: string;
  step_id: string | null;
  node_id: string;
  node_name: string;
  error: ExecutionError & Record<string, unknown>;
  input: unknown;
  status: "open" | "retried" | "discarded";
  created_at: string;
  resolved_at: string | null;
};

export type NodeTestResult = {
  status: "succeeded" | "failed";
  output: unknown;
  ports: string[];
  vars: Record<string, unknown> | null;
  events: { event: string; payload: unknown }[];
  suspend_until: string | null;
  logs: { level: string; message: string; data: Record<string, unknown> }[];
  error: (ExecutionError & { retryable?: boolean; details?: unknown }) | null;
  duration_ms: number;
};

/* Vault, variables, events, keys, audit ---------------------------------------------------- */

export type Credential = {
  id: string;
  name: string;
  type: string;
  description: string;
  public_fields: Record<string, unknown>;
  secret_fields: string[];
  key_provider: string;
  version: number;
  used_by: string[];
  created_at: string;
  updated_at: string;
  last_used_at: string | null;
};

export type Variable = { key: string; value: string; description: string; updated_at: string };

export type BusEvent = {
  id: string;
  name: string;
  payload: unknown;
  source: "api" | "workflow" | "system";
  source_execution_id: string | null;
  depth: number;
  matched: number;
  created_at: string;
};

export type ApiKey = {
  id: string;
  name: string;
  prefix: string;
  role: Role;
  created_at: string;
  last_used_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
};

export type ApiKeyCreated = ApiKey & { key: string };

export type AuditEvent = {
  id: string;
  action: string;
  target_type: string;
  target_id: string | null;
  details: Record<string, unknown>;
  actor_type: "user" | "api_key" | "system";
  actor_name: string | null;
  created_at: string;
};

/* Dashboard ---------------------------------------------------------------------------------- */

export type DashboardWindow = "24h" | "7d" | "14d" | "30d";

export type Dashboard = {
  window: DashboardWindow;
  timezone: string;
  generated_at: string;
  totals: { total: number; succeeded: number; failed: number; cancelled: number; in_progress: number };
  success_rate: number | null;
  p50_ms: number | null;
  p95_ms: number | null;
  volume: { start: string; label: string; succeeded: number; failed: number; cancelled: number; in_progress: number }[];
  slowest: { workflow_id: string; name: string; runs: number; p95_ms: number; avg_ms: number }[];
  busiest: { workflow_id: string; name: string; runs: number; failed: number; failure_rate: number }[];
  recent_failures: {
    execution_id: string;
    workflow_id: string;
    workflow_name: string;
    code: string | null;
    message: string | null;
    node_id: string | null;
    finished_at: string | null;
  }[];
  queue: { executions_queued: number; steps_ready: number; steps_running: number; steps_waiting: number };
  dead_letters_open: number;
  workflows: number;
  active_workflows: number;
  workers: { id: string; hostname: string; busy: number; concurrency: number; leader: boolean; version: string; seen_at: string }[];
  upcoming: { workflow_id: string; workflow_name: string; node_id: string; kind: string; next_fire_at: string }[];
};
