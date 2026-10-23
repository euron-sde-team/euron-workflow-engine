import { expect, test } from "@playwright/test";

import { WORKSPACE, signIn } from "../helpers";

test("build a workflow on the canvas, test a node, run the draft and publish it", async ({
  page,
}) => {
  await signIn(page, "editor");
  await page.goto(`/w/${WORKSPACE}/workflows`);
  await page.getByTestId("new-workflow").click();
  const name = `Greet a customer ${Date.now()}`;
  await page.getByLabel("Name").fill(name);
  await page.getByTestId("create-workflow").click();

  // A new workflow starts with a manual trigger.
  await expect(page.getByTestId("workflow-name")).toHaveText(name);
  await page.getByTestId("node-manual_trigger").click();

  // Clicking a palette entry adds the node after the selected one and opens its settings.
  await page.getByTestId("palette-core.transform").click();
  await expect(page.getByTestId("node-transform")).toBeVisible();
  await expect(page.getByTestId("issues-button")).toContainText("1 problem");
  await page.locator("#field-expression").fill("{greeting: 'Hello', who: trigger.name}");
  await expect(page.getByTestId("issues-button")).toContainText("No problems");
  await expect(page.getByTestId("save-state")).toContainText("Saved");

  // A single-node test run shows the output without storing anything.
  await page.getByRole("tab", { name: "Test" }).click();
  await page.getByTestId("test-node").click();
  await expect(page.getByTestId("test-result")).toContainText("Hello");

  // Run the whole draft with a payload, then open the execution it created.
  await page.getByTestId("run-draft").click();
  await page.locator("#run-payload").fill('{"name": "Ada Lovelace"}');
  await page.getByTestId("confirm-run").click();
  await expect(page.getByTestId("run-panel")).toContainText("Succeeded", { timeout: 30_000 });
  await page.getByRole("link", { name: "Open execution" }).click();
  await expect(page.getByText("Draft test run")).toBeVisible();
  await page.getByRole("button", { name: /^Transform/ }).click();
  await expect(page.getByTestId("step-panel")).toContainText("Ada Lovelace");

  // Publish version 1 and turn it on.
  await page.getByRole("link", { name: "Open workflow" }).click();
  await page.getByTestId("publish").click();
  await page.getByLabel("What changed").fill("First version");
  await page.getByTestId("confirm-publish").click();
  await expect(page.getByText("Version 1")).toBeVisible();
  await expect(page.getByRole("switch", { name: "Active" })).toBeChecked();
});

test("a template becomes a working draft with its credentials resolved", async ({ page }) => {
  await signIn(page, "editor");
  await page.goto(`/w/${WORKSPACE}/templates`);
  await page
    .getByTestId("template-uptime-monitor")
    .getByRole("button", { name: "Preview" })
    .click();
  // Every credential and variable the template needs already exists in the demo workspace.
  await expect(page.getByText("Add it")).toHaveCount(0);
  await page.getByTestId("use-template").click();

  await expect(page).toHaveURL(new RegExp(`/w/${WORKSPACE}/workflows/[0-9a-f-]+$`));
  await expect(page.getByTestId("issues-button")).toContainText("No problems");
  await expect(page.locator("[data-testid^='node-']").first()).toBeVisible();
});

test("a viewer can look but not change anything", async ({ page }) => {
  await signIn(page, "viewer");
  await page.goto(`/w/${WORKSPACE}/workflows`);
  await expect(page.getByTestId("workflow-link").first()).toBeVisible();
  await expect(page.getByTestId("new-workflow")).toHaveCount(0);

  await page.getByTestId("workflow-link").first().click();
  await expect(page.getByTestId("canvas")).toBeVisible();
  await expect(page.getByTestId("publish")).toHaveCount(0);
  await expect(page.getByTestId("run-draft")).toHaveCount(0);
});
