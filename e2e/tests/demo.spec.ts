import { expect, test } from "@playwright/test";
import { exploreDemo } from "./helpers";

test("the demo opens a read-only manager view", async ({ page }) => {
  await exploreDemo(page);
  await expect(page.getByRole("note")).toContainText("read-only demo");
  await page.getByRole("link", { name: "Dashboard" }).click();
  await expect(page.getByText("Incident volume")).toBeVisible();
  await expect(page.locator("svg polyline")).toHaveCount(2);
});

test("the demo can browse and ask, but not change anything", async ({ page }) => {
  await exploreDemo(page);
  await page.getByRole("link", { name: "New incident" }).click();
  await page.getByLabel("Summary").fill("Demo should not save this");
  await page.getByLabel("What is happening?").fill("This ticket must be refused because the demo is read-only.");
  await page.getByRole("button", { name: /Submit incident/ }).click();
  await expect(page.getByRole("alert")).toContainText("read-only");

  await page.getByRole("link", { name: "Assistant", exact: true }).click();
  await page.getByLabel("Message").fill("how long do we have to fix a P2 ticket");
  await page.getByLabel("Message").press("Enter");
  // Wait for any outcome first, so a failure reports what the page said instead of a timeout.
  const outcome = page.getByText(/Based on the retrieved sources|could not find enough evidence/).or(page.getByRole("alert"));
  await expect(outcome.first()).toBeVisible({ timeout: 60_000 });
  await expect(page.locator("main")).toContainText("KB-1901");
});

test("a ticket explains what moved its risk score", async ({ page }) => {
  await exploreDemo(page);
  await page.locator("tbody tr a").first().click();
  await expect(page.getByText("AI triage")).toBeVisible();
  const reasons = page.getByText("What moved the score, compared with a typical ticket");
  await expect(reasons).toBeVisible();
  await expect(page.getByText(/[+−]\d+ pts/).first()).toBeVisible();
});

test("notification charts cover every type", async ({ page }) => {
  await exploreDemo(page);
  await page.getByRole("link", { name: /Notifications/ }).click();
  await expect(page.getByRole("list", { name: "Notifications by type" }).getByRole("img")).toHaveCount(8);
});
