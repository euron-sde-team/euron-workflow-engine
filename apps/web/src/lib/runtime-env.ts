/**
 * Runtime configuration served by /env.js, so one image runs in every environment.
 * The server half (`serializeEnv`) is used by the route handler; the browser half reads
 * the global it defines.
 */
export type RuntimeEnv = {
  apiUrl: string;
  productName: string;
};

export const ENV_GLOBAL = "__WFE__";

const DEFAULTS: RuntimeEnv = {
  apiUrl: "http://localhost:8130",
  productName: "Euron WorkflowEngine",
};

export function serializeEnv(source: Record<string, string | undefined>): string {
  const env: RuntimeEnv = {
    apiUrl: (source.API_URL || DEFAULTS.apiUrl).replace(/\/+$/, ""),
    productName: source.PRODUCT_NAME || DEFAULTS.productName,
  };
  // JSON.stringify output is valid JavaScript; escaping "<" keeps it inert inside HTML too.
  return `window.${ENV_GLOBAL}=${JSON.stringify(env).replace(/</g, "\\u003c")};`;
}

export function runtimeEnv(): RuntimeEnv {
  if (typeof window === "undefined") return DEFAULTS;
  const value = (window as unknown as Record<string, RuntimeEnv | undefined>)[ENV_GLOBAL];
  return { ...DEFAULTS, ...value };
}
