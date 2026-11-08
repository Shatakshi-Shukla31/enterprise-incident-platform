import { expect, type Page } from "@playwright/test";

export const demoPassword = process.env.E2E_DEMO_PASSWORD;
export const adminCode = process.env.E2E_ADMIN_CODE;
export const newPassword = "a-long-enough-password";

/** The account cards and mode switch are radio buttons styled as cards. */
export async function choose(page: Page, name: string | RegExp) {
  await page.locator("label", { has: page.getByRole("radio", { name }) }).click();
}

export async function openSignIn(page: Page) {
  await page.goto("/");
  await expect(page.getByRole("radio", { name: /^User/ })).toBeAttached();
}

export async function exploreDemo(page: Page) {
  await openSignIn(page);
  await page.getByRole("button", { name: "Explore the demo" }).click();
  await expect(page.getByRole("heading", { name: "Incidents" })).toBeVisible();
}

export async function createAccount(page: Page, email: string, code?: string) {
  await choose(page, code ? /^Admin/ : /^User/);
  await choose(page, "Create account");
  await page.getByLabel("Full name").fill("Test Person");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel(/^Password/).fill(newPassword);
  await page.getByLabel("Confirm password", { exact: true }).fill(newPassword);
  if (code) await page.getByLabel(/^Admin access code/).fill(code);
  await page.getByRole("button", { name: "Create account" }).click();
}

export const uniqueEmail = (label: string) => `e2e-${label}-${Date.now()}@example.com`;

export async function horizontalOverflow(page: Page) {
  return page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
}
