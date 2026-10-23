import { expect, test } from "@playwright/test";

import { WORKSPACE, signIn, toast } from "../helpers";

test("publishing an event starts the workflows that listen to it", async ({ page }) => {
  await signIn(page, "editor");
  await page.goto(`/w/${WORKSPACE}/events`);
  await page.getByLabel("Name", { exact: true }).fill("lead.created");
  await page
    .getByLabel("Payload")
    .fill(
      '{"lead_id": "L-900", "name": "Noah Berg", "email": "noah@fjordline.example.com", "domain": "fjordline.example.com"}',
    );
  await page.getByTestId("publish-event").click();
  await expect(toast(page, "Started 1 workflow")).toBeVisible();
  await expect(page.getByTestId("event-list").getByText("lead.created").first()).toBeVisible();

  await page.goto(`/w/${WORKSPACE}/executions?trigger=event`);
  await expect(page.getByTestId("execution-link").first()).toBeVisible();
});

test("credentials are write-only: stored, rotated and deleted without ever being shown", async ({
  page,
}) => {
  await signIn(page, "editor");
  const name = `Partner API ${Date.now()}`;
  const token = `tok-e2e-${Date.now()}-do-not-display`;
  await page.goto(`/w/${WORKSPACE}/credentials`);
  await page.getByTestId("new-credential").click();
  await page.getByTestId("credential-type-http_bearer").click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Name", { exact: true }).fill(name);
  await dialog.locator("#credential-token").fill(token);
  await page.getByTestId("save-credential").click();
  await expect(page.getByText(`Created ${name}`)).toBeVisible();
  const row = page.getByTestId("credential-row").filter({ hasText: name });
  await expect(row).toContainText("Not used by any workflow");
  await expect(page.locator("body")).not.toContainText(token);

  // Editing never shows the secret; leaving it blank keeps the stored value.
  await row.getByRole("button", { name: `Actions for ${name}` }).click();
  await page.getByRole("menuitem", { name: "Edit or rotate" }).click();
  await expect(dialog.locator("#credential-token")).toHaveValue("");
  await dialog.getByLabel("Notes").fill("Rotated every quarter");
  await page.getByTestId("save-credential").click();
  await expect(row).toContainText("Rotated every quarter");
  await expect(row).toContainText("v2");

  await row.getByRole("button", { name: `Actions for ${name}` }).click();
  await page.getByRole("menuitem", { name: "Delete" }).click();
  await page.getByTestId("confirm-delete-credential").click();
  await expect(page.getByText(`Deleted ${name}`)).toBeVisible();
  await expect(row).toHaveCount(0);
});

test("owners manage variables and API keys, and every change lands in the audit log", async ({
  page,
}) => {
  await signIn(page, "owner");
  await page.goto(`/w/${WORKSPACE}/settings`);

  await page.getByRole("tab", { name: "Variables" }).click();
  await page.getByTestId("new-variable").click();
  const key = `E2E_${String(Date.now()).slice(-6)}`;
  await page.locator("#variable-key").fill(key);
  await page.locator("#variable-value").fill("https://partner.example.com/v1");
  await page.getByTestId("save-variable").click();
  await expect(page.getByText(`Saved ${key}`)).toBeVisible();
  await expect(page.getByRole("tabpanel").locator("li").filter({ hasText: key })).toContainText(
    "https://partner.example.com/v1",
  );

  await page.getByRole("tab", { name: "API keys" }).click();
  await page.getByRole("button", { name: "Create key" }).click();
  await page.locator("#key-name").fill("E2E nightly job");
  await page.getByRole("dialog").getByRole("button", { name: "Create key" }).click();
  await expect(page.getByLabel("API key", { exact: true })).toContainText("wfk_");
  await page.getByRole("button", { name: "Done" }).click();
  const keyRow = page
    .getByRole("tabpanel")
    .locator("li")
    .filter({ hasText: "E2E nightly job" })
    .first();
  await keyRow.getByRole("button", { name: "Revoke" }).click();
  await expect(keyRow).toContainText("Revoked");

  await page.getByRole("tab", { name: "Audit log" }).click();
  await expect(page.getByTestId("audit-log")).toContainText("revoked the API key E2E nightly job");
});
