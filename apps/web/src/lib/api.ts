import { runtimeEnv } from "@/lib/runtime-env";

/** A failed API call, carrying the server's error envelope. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly requestId: string | null = null,
    readonly details: unknown = undefined,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type Envelope = {
  error?: { code?: string; message?: string; request_id?: string; details?: unknown };
};

export function errorFrom(status: number, body: unknown): ApiError {
  const error = (body as Envelope | null)?.error;
  return new ApiError(
    status,
    error?.code ?? (status >= 500 ? "server_error" : "request_failed"),
    error?.message ?? "The request failed. Try again.",
    error?.request_id ?? null,
    error?.details,
  );
}

type RequestOptions = Omit<RequestInit, "body"> & { json?: unknown; body?: BodyInit };

export function apiUrl(path: string): string {
  return `${runtimeEnv().apiUrl}${path}`;
}

/** JSON over fetch with the session cookie; throws ApiError on any non-2xx response. */
export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { json, headers, ...rest } = options;
  let response: Response;
  try {
    response = await fetch(apiUrl(path), {
      credentials: "include",
      ...rest,
      headers: {
        accept: "application/json",
        ...(json !== undefined ? { "content-type": "application/json" } : {}),
        ...headers,
      },
      body: json !== undefined ? JSON.stringify(json) : rest.body,
    });
  } catch {
    throw new ApiError(0, "network_error", "Cannot reach the WorkflowEngine API. Is it running?");
  }
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = null;
  }
  if (!response.ok) throw errorFrom(response.status, body);
  return body as T;
}

export const ws = (workspace: string) => `/api/v1/workspaces/${encodeURIComponent(workspace)}`;
