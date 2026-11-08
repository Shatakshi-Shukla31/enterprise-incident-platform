import { expect, test } from "@playwright/test";
import { adminCode, choose, createAccount, demoPassword, newPassword, openSignIn, uniqueEmail } from "./helpers";

test("offers both account types, both actions and the demo", async ({ page }) => {
  await openSignIn(page);
  await expect(page.getByRole("radio", { name: /^User/ })).toBeChecked();
  await expect(page.getByRole("radio", { name: /^Admin/ })).not.toBeChecked();
  await expect(page.getByRole("radio", { name: "Create account" })).toBeAttached();
  await expect(page.getByRole("button", { name: "Explore the demo" })).toBeVisible();
});

test("a new user account is a requester and can sign in again", async ({ page }) => {
  const email = uniqueEmail("user");
  await openSignIn(page);
  await createAccount(page, email);
  await expect(page.getByRole("heading", { name: "Incidents" })).toBeVisible();
  const sidebar = page.locator("aside");
  await expect(sidebar).toContainText("Requester");
  await expect(sidebar.getByRole("link", { name: "Dashboard" })).toHaveCount(0);

  await page.getByRole("button", { name: "Sign out" }).click();
  await page.getByLabel("Email").fill(email);
  await page.getByLabel(/^Password/).fill(newPassword);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Incidents" })).toBeVisible();
});

test("a requester cannot use the admin sign-in", async ({ page }) => {
  const email = uniqueEmail("blocked");
  await openSignIn(page);
  await createAccount(page, email);
  await page.getByRole("button", { name: "Sign out" }).click();
  await choose(page, /^Admin/);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel(/^Password/).fill(newPassword);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toContainText("no staff access");
});

test("a wrong admin access code creates nothing", async ({ page }) => {
  await openSignIn(page);
  await createAccount(page, uniqueEmail("guess"), "a-wrong-guess");
  await expect(page.getByRole("alert")).toContainText("not valid");
  await expect(page.getByRole("heading", { name: "Incidents" })).toHaveCount(0);
});

test("the right admin access code creates an admin", async ({ page }) => {
  test.skip(!adminCode, "Set E2E_ADMIN_CODE to the server's ADMIN_SIGNUP_CODE");
  await openSignIn(page);
  await createAccount(page, uniqueEmail("admin"), adminCode);
  await expect(page.locator("aside").getByRole("link", { name: "Users" })).toBeVisible();
});

test("a demo staff account signs in through Admin", async ({ page }) => {
  test.skip(!demoPassword, "Set E2E_DEMO_PASSWORD to the seeded DEMO_PASSWORD");
  await openSignIn(page);
  await choose(page, /^Admin/);
  await page.getByLabel("Email").fill("manager@example.com");
  await page.getByLabel(/^Password/).fill(demoPassword!);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("link", { name: "Dashboard" })).toBeVisible();
});
