import { createHash, createHmac } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const API_URL = process.env.API_URL ?? "http://localhost:8130";
export const PASSWORD = process.env.DEMO_PASSWORD ?? "";
export const WORKSPACE = "northwind";

export const PEOPLE = {
  owner: { email: "maya@northwind.example.com", name: "Maya Patel" },
  editor: { email: "ravi@northwind.example.com", name: "Ravi Shah" },
  viewer: { email: "lena@northwind.example.com", name: "Lena Fischer" },
} as const;

export function requirePassword(): string {
  if (!PASSWORD) throw new Error("Set DEMO_PASSWORD (make e2e reads it from deploy/compose/.env)");
  return PASSWORD;
}

const SESSIONS = path.resolve(__dirname, ".auth");

/** Sign in through the form, exactly as a person does. */
export async function signInWithForm(
  page: Page,
  who: keyof typeof PEOPLE = "owner",
): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(PEOPLE[who].email);
  await page.getByLabel("Password").fill(requirePassword());
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/w\/[^/]+\/dashboard/);
}

/**
 * A signed-in page for one demo person. The session cookie from the first form sign-in is
 * reused by later tests: the API allows ten sign-ins a minute per address, and the suites
 * would otherwise trip that limit themselves. A stale cookie (after `make down`) falls back
 * to the form.
 */
export async function signIn(page: Page, who: keyof typeof PEOPLE = "owner"): Promise<void> {
  const saved = path.join(SESSIONS, `${who}.json`);
  if (existsSync(saved)) {
    await page.context().addCookies(JSON.parse(readFileSync(saved, "utf8")));
    await page.goto("/");
    await page.waitForURL(/\/(w\/[^/]+\/dashboard|login)/);
    if (!page.url().includes("/login")) return;
    await page.context().clearCookies();
  }
  await signInWithForm(page, who);
  mkdirSync(SESSIONS, { recursive: true });
  writeFileSync(saved, JSON.stringify(await page.context().cookies()));
}

/** Wait until the page has settled: no pending network, fonts ready, transitions finished. */
export async function settle(page: Page): Promise<void> {
  await page.waitForLoadState("networkidle");
  await page.evaluate(async () => {
    await document.fonts.ready;
    // Spinners and pulsing dots repeat forever; only wait for animations that end.
    const finite = document
      .getAnimations()
      .filter((animation) => animation.effect?.getTiming().iterations !== Infinity);
    await Promise.all(finite.map((animation) => animation.finished.catch(() => undefined)));
  });
}

/** A toast notification with the given text (sonner renders them as list items). */
export function toast(page: Page, text: string) {
  return page.locator("[data-sonner-toast]").filter({ hasText: text });
}

/** GET a workspace API path with the page's session cookie. */
export async function apiGet<T>(page: Page, apiPath: string): Promise<T> {
  const response = await page.request.get(`${API_URL}/api/v1/workspaces/${WORKSPACE}${apiPath}`);
  expect(response.ok(), apiPath).toBeTruthy();
  return (await response.json()) as T;
}

/** The secret the demo seed derives for the shop webhook (see demo/seed.py `derived`). */
export function shopSecret(): string {
  const digest = createHash("sha256").update(`${requirePassword()}:shop`).digest("hex");
  return `whsec_${digest.slice(0, 32)}`;
}

/** Send a webhook signed the way the shop does: HMAC-SHA256 over the raw body. */
export async function sendShopOrder(
  request: APIRequestContext,
  body: Record<string, unknown>,
  idempotencyKey: string,
): Promise<{ execution_id: string; status: string; duplicate: boolean }> {
  const raw = JSON.stringify(body);
  const signature = createHmac("sha256", shopSecret()).update(raw).digest("hex");
  const response = await request.post(`${API_URL}/hooks/${WORKSPACE}/shop/orders`, {
    data: raw,
    headers: {
      "content-type": "application/json",
      "x-shop-signature": `sha256=${signature}`,
      "idempotency-key": idempotencyKey,
    },
  });
  expect(response.status(), await response.text()).toBeLessThan(300);
  return (await response.json()) as { execution_id: string; status: string; duplicate: boolean };
}
