/**
 * README screenshots (1440x900 at 2x) and tour frames, from the seeded demo workspace.
 * Every image shows the real stack: nothing here is mocked.
 */
import { mkdirSync, rmSync } from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { WORKSPACE, apiGet, settle, signIn } from "../helpers";

const SHOTS = path.resolve(__dirname, "../../docs/assets/screenshots");
const FRAMES = path.resolve(__dirname, "../.capture/frames");
rmSync(FRAMES, { recursive: true, force: true });
mkdirSync(SHOTS, { recursive: true });
mkdirSync(FRAMES, { recursive: true });

type Item = { id: string; name?: string; workflow_name?: string; resume_count?: number };

let frame = 0;
async function shot(page: Page, name: string): Promise<void> {
  await settle(page);
  // A clicked tab or button keeps a focus ring; screenshots show the page at rest.
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
}
async function tourFrame(page: Page, holdMs = 1600): Promise<void> {
  frame += 1;
  const file = path.join(FRAMES, `${String(frame).padStart(3, "0")}-${holdMs}.png`);
  await page.screenshot({ path: file, scale: "css" });
}

async function workflowId(page: Page, search: string): Promise<string> {
  const found = await apiGet<{ items: Item[] }>(
    page,
    `/workflows?search=${encodeURIComponent(search)}`,
  );
  expect(found.items.length, search).toBeGreaterThan(0);
  return found.items[0]!.id;
}

test.describe.configure({ mode: "serial" });
// Captures run on a busy laptop as often as on CI: allow slow pages rather than flake.
test.setTimeout(240_000);

test("sign-in page", async ({ page }) => {
  await page.goto("/login");
  await settle(page);
  await page.screenshot({ path: path.join(SHOTS, "01-sign-in.png") });
  await tourFrame(page, 1400);
});

test("dashboard, workflows, editor, executions and operations", async ({ page }) => {
  await signIn(page, "owner");
  const base = `/w/${WORKSPACE}`;

  await page.goto(`${base}/dashboard`);
  await expect(page.getByText("Success rate")).toBeVisible();
  await page.waitForTimeout(900); // the volume chart animates in
  await shot(page, "02-dashboard");
  await tourFrame(page, 2400);

  await page.goto(`${base}/workflows`);
  await expect(page.getByTestId("workflow-link").first()).toBeVisible();
  await shot(page, "03-workflows");
  await tourFrame(page, 2000);

  // The order workflow in the editor: the whole graph first, then the retrying HTTP node.
  await page.goto(`${base}/workflows/${await workflowId(page, "Ship paid orders")}`);
  await expect(page.getByTestId("canvas")).toBeVisible();
  await page.waitForTimeout(500);
  await shot(page, "04-editor");
  await tourFrame(page, 2400);

  await page.getByText("Create shipment", { exact: true }).click();
  await expect(page.getByTestId("inspector")).toBeVisible();
  await page.getByRole("tab", { name: "Settings" }).click();
  await shot(page, "05-editor-retries");
  await tourFrame(page, 2400);

  await page.goto(`${base}/executions`);
  await expect(page.getByTestId("execution-link").first()).toBeVisible();
  await shot(page, "06-executions");
  await tourFrame(page, 2000);

  // A succeeded order run that needed a retry: graph, timeline and the step's output.
  const orders = await apiGet<{ items: Item[] }>(
    page,
    `/executions?workflow_id=${await workflowId(page, "Ship paid orders")}&status=succeeded&limit=5`,
  );
  await page.goto(`${base}/executions/${orders.items[0]!.id}`);
  await expect(page.getByTestId("timeline")).toBeVisible();
  await page.getByRole("button", { name: /^Create shipment/ }).click();
  await expect(page.getByTestId("step-panel")).toBeVisible();
  await page.waitForTimeout(600);
  await shot(page, "07-execution");
  await tourFrame(page, 2800);

  // A failed billing batch: the error, the failing step, its input.
  const failed = await apiGet<{ items: Item[] }>(page, "/executions?status=failed&limit=10");
  const billing =
    failed.items.find((e) => e.workflow_name?.includes("invoices")) ?? failed.items[0]!;
  await page.goto(`${base}/executions/${billing.id}`);
  await expect(page.getByTestId("step-panel")).toBeVisible();
  await page.waitForTimeout(600);
  await shot(page, "08-execution-failed");
  await tourFrame(page, 2200);

  await page.goto(`${base}/dead-letters`);
  await expect(page.getByTestId("dead-letter").first()).toBeVisible();
  await page.getByRole("button", { name: "Show details" }).first().click();
  await shot(page, "09-dead-letters");
  await tourFrame(page, 1800);

  await page.goto(`${base}/templates`);
  await expect(page.getByTestId("template-order-fulfillment")).toBeVisible();
  await shot(page, "10-templates");
  await page.getByTestId("template-lead-routing").getByRole("button", { name: "Preview" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.waitForTimeout(700);
  await shot(page, "11-template-preview");
  await tourFrame(page, 2200);
  await page.keyboard.press("Escape");

  await page.goto(`${base}/credentials`);
  await expect(page.getByTestId("credential-row").first()).toBeVisible();
  await shot(page, "12-credentials");
  await tourFrame(page, 1800);

  await page.goto(`${base}/events`);
  await expect(page.getByTestId("event-list")).toBeVisible();
  await page.getByTestId("event-list").getByRole("button").first().click();
  await shot(page, "13-events");
  await tourFrame(page, 1800);

  await page.goto(`${base}/settings`);
  await page.getByRole("tab", { name: "Audit log" }).click();
  await expect(page.getByTestId("audit-log")).toBeVisible();
  await shot(page, "14-audit-log");
  await tourFrame(page, 1600);
});

test("dark theme", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await signIn(page, "owner");
  await page.goto(`/w/${WORKSPACE}/workflows/${await workflowId(page, "Daily low-stock report")}`);
  await expect(page.getByTestId("canvas")).toBeVisible();
  await page.waitForTimeout(600);
  await shot(page, "15-dark-editor");
});
