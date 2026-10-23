/**
 * Exploratory QA crawl: every page at desktop and mobile widths, signed in as the demo owner.
 *
 * A page fails on console errors, uncaught exceptions, failed or 4xx/5xx requests, sideways
 * scrolling, broken internal links and serious or critical axe violations (WCAG 2 A and AA).
 * A full-page capture of every page lands in e2e/.qa/ for a visual review.
 */
import { mkdirSync } from "node:fs";
import path from "node:path";

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { WORKSPACE, apiGet, settle, signIn } from "../helpers";

const OUT = path.resolve(__dirname, "../.qa");
mkdirSync(OUT, { recursive: true });

const VIEWPORTS = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "mobile", width: 390, height: 844 },
] as const;

const SETTINGS_TABS = ["General", "Variables", "Members", "API keys", "Audit log"];

type Crawl = { page: Page; viewport: string; problems: string[]; links: Set<string> };
type Item = { id: string; status?: string };

function watch(page: Page, viewport: string): Crawl {
  const crawl: Crawl = { page, viewport, problems: [], links: new Set() };
  page.on("console", (message) => {
    if (message.type() === "error") crawl.problems.push(`console: ${message.text()}`);
  });
  page.on("pageerror", (error) => crawl.problems.push(`uncaught: ${error.message}`));
  page.on("requestfailed", (request) => {
    const reason = request.failure()?.errorText ?? "";
    // Aborted requests are navigations away or cancelled queries, not failures.
    if (!reason.includes("ERR_ABORTED"))
      crawl.problems.push(`request failed: ${request.url()} ${reason}`);
  });
  page.on("response", (response) => {
    if (response.status() >= 400)
      crawl.problems.push(`HTTP ${response.status()}: ${response.url()}`);
  });
  return crawl;
}

async function inspect(crawl: Crawl, name: string): Promise<void> {
  const { page } = crawl;
  await settle(page);
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  if (overflow > 1) crawl.problems.push(`${name}: scrolls sideways by ${overflow}px`);

  const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  for (const violation of axe.violations) {
    if (violation.impact !== "serious" && violation.impact !== "critical") continue;
    const nodes = violation.nodes
      .slice(0, 3)
      .map((node) => node.target.join(" "))
      .join(" | ");
    crawl.problems.push(`${name}: axe ${violation.id} (${violation.impact}) at ${nodes}`);
  }

  const hrefs = await page.$$eval('a[href^="/"]', (anchors) =>
    anchors.map((a) => a.getAttribute("href") ?? ""),
  );
  for (const href of hrefs) crawl.links.add(href.split("#")[0]);
  await page.screenshot({ path: path.join(OUT, `${crawl.viewport}-${name}.png`), fullPage: true });
}

async function visit(crawl: Crawl, name: string, url: string): Promise<void> {
  const response = await crawl.page.goto(url);
  expect(response?.status(), url).toBeLessThan(400);
  await inspect(crawl, name);
}

for (const viewport of VIEWPORTS) {
  test.describe(`${viewport.name} ${viewport.width}x${viewport.height}`, () => {
    test.use({ viewport: { width: viewport.width, height: viewport.height } });

    test("signed-out pages", async ({ page }) => {
      const crawl = watch(page, viewport.name);
      await visit(crawl, "sign-in", "/login");
      const missing = await page.goto("/no-such-page");
      expect(missing?.status()).toBe(404);
      await inspect(crawl, "not-found");

      // The 404 itself is expected; anything else is a problem.
      expect(crawl.problems.filter((problem) => !problem.includes("404"))).toEqual([]);
    });

    test("every workspace page", async ({ page }) => {
      await signIn(page, "owner");
      const crawl = watch(page, viewport.name);
      const base = `/w/${WORKSPACE}`;
      const workflows = await apiGet<{ items: Item[] }>(page, "/workflows?limit=100");
      const failed = await apiGet<{ items: Item[] }>(page, "/executions?status=failed&limit=1");
      const succeeded = await apiGet<{ items: Item[] }>(
        page,
        "/executions?status=succeeded&limit=1",
      );
      expect(workflows.items.length).toBeGreaterThan(0);

      await visit(crawl, "dashboard", `${base}/dashboard`);
      await visit(crawl, "workflows", `${base}/workflows`);
      await visit(crawl, "editor", `${base}/workflows/${workflows.items[0]!.id}`);
      await visit(crawl, "executions", `${base}/executions`);
      if (failed.items[0])
        await visit(crawl, "execution-failed", `${base}/executions/${failed.items[0].id}`);
      if (succeeded.items[0])
        await visit(crawl, "execution-succeeded", `${base}/executions/${succeeded.items[0].id}`);
      await visit(crawl, "templates", `${base}/templates`);
      await visit(crawl, "credentials", `${base}/credentials`);
      await visit(crawl, "events", `${base}/events`);
      await visit(crawl, "dead-letters", `${base}/dead-letters`);
      await visit(crawl, "settings", `${base}/settings`);
      for (const tab of SETTINGS_TABS) {
        await page.getByRole("tab", { name: tab }).click();
        await inspect(crawl, `settings-${tab.toLowerCase().replace(" ", "-")}`);
      }

      for (const link of crawl.links) {
        const response = await page.request.get(link);
        if (response.status() >= 400)
          crawl.problems.push(`broken link: ${link} (${response.status()})`);
      }
      expect(crawl.problems).toEqual([]);
    });
  });
}
