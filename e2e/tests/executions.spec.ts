import { expect, test } from "@playwright/test";

import { WORKSPACE, apiGet, sendShopOrder, signIn } from "../helpers";

test("a signed webhook runs the order workflow, retries the busy API and archives the order", async ({
  page,
  request,
}) => {
  await signIn(page, "owner");
  const orderId = `SO-${String(Date.now()).slice(-6)}`;
  const body = {
    order_id: orderId,
    customer: { name: "Ines Moreau", email: "ines@trailhead.example.com", tier: "gold" },
    items: [{ sku: "TENT-2P", title: "Two-person tent", qty: 3, price: 249 }],
    total: 747,
  };
  const first = await sendShopOrder(request, body, `e2e-${orderId}`);
  // The shop retried the delivery: same idempotency key, same execution.
  const again = await sendShopOrder(request, body, `e2e-${orderId}`);
  expect(again.execution_id).toBe(first.execution_id);
  expect(again.duplicate).toBe(true);

  await page.goto(`/w/${WORKSPACE}/executions/${first.execution_id}`);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Succeeded", {
    timeout: 60_000,
  });
  await expect(page.getByTestId("execution-graph")).toBeVisible();
  // The fulfillment API answers 503 to a first attempt; the step retried and succeeded.
  await page.getByRole("button", { name: /^Create shipment/ }).click();
  await expect(page.getByTestId("step-panel")).toContainText("2 of");
  await expect(page.getByTestId("step-panel")).toContainText(orderId);
});

test("a waiting execution can be cancelled", async ({ page }) => {
  await signIn(page, "owner");
  const waiting = await apiGet<{ items: { id: string }[] }>(
    page,
    "/executions?status=waiting&limit=1",
  );
  expect(waiting.items.length, "the demo leaves follow-ups waiting").toBeGreaterThan(0);
  await page.goto(`/w/${WORKSPACE}/executions/${waiting.items[0]!.id}`);
  const title = page.getByRole("heading", { level: 1 });
  await expect(title).toContainText("Waiting");
  await page.getByTestId("cancel-execution").click();
  await expect(page.getByText("Execution cancelled")).toBeVisible();
  await expect(title).toContainText("Cancelled");
});

test("the executions list filters by status and opens a failed run at the failing step", async ({
  page,
}) => {
  await signIn(page, "owner");
  await page.goto(`/w/${WORKSPACE}/executions`);
  await page.getByLabel("Filter by status").selectOption("failed");
  await expect(page).toHaveURL(/status=failed/);
  await page.getByTestId("execution-link").first().click();
  await expect(page.getByRole("alert").first()).toContainText("Failed");
  // The failed step opens on its own, with its input and error.
  await expect(page.getByTestId("step-panel")).toContainText("Failed");
});

test("a dead letter resumes its execution from the failed step", async ({ page }) => {
  await signIn(page, "owner");
  await page.goto(`/w/${WORKSPACE}/dead-letters`);
  const letters = page.getByTestId("dead-letter");
  await expect(letters.first()).toBeVisible();
  const before = await letters.count();
  await page.getByTestId("retry-dead-letter").first().click();
  await expect(page.getByText("Resumed from the failed step")).toBeVisible();
  await expect(letters).toHaveCount(before - 1);
});
