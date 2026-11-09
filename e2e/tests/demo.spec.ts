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
  // Page changes render in a transition, so the old page can still be showing. Its description
  // hint mentions "error messages", so the label match must be exact and the new page present.
  await expect(page.getByRole("button", { name: "New conversation" })).toBeVisible();
  const box = page.getByLabel("Message", { exact: true });
  await box.fill("how long do we have to fix a P2 ticket");
  const reply = page.waitForResponse((response) => response.url().includes("/ai/chat"), { timeout: 90_000 });
  await box.press("Enter");
  const response = await reply;
  expect(response.status(), (await response.text()).slice(0, 300)).toBe(200);
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
