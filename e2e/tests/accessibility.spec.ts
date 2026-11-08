import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { exploreDemo, horizontalOverflow, openSignIn } from "./helpers";

// Serious and critical problems fail the build. Minor ones are reported but tolerated.
async function seriousProblems(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  return results.violations
    .filter((item) => item.impact === "serious" || item.impact === "critical")
    .map((item) => `${item.id}: ${item.nodes.map((node) => node.target.join(" ")).slice(0, 3).join(", ")}`);
}

for (const scheme of ["light", "dark"] as const) {
  test(`sign-in page has no serious accessibility problems in ${scheme} mode`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme });
    await openSignIn(page);
    expect(await seriousProblems(page)).toEqual([]);
  });

  test(`main pages have no serious accessibility problems in ${scheme} mode`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme });
    await exploreDemo(page);
    for (const name of ["Incidents", "Dashboard", "Notifications"]) {
      await page.getByRole("link", { name: new RegExp(`^${name}`) }).click();
      await page.waitForLoadState("networkidle");
      expect(await seriousProblems(page), name).toEqual([]);
    }
  });
}

test("works at phone width without sideways scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openSignIn(page);
  expect(await horizontalOverflow(page)).toBeLessThanOrEqual(0);
  await exploreDemo(page);
  await page.getByRole("link", { name: /Notifications/ }).click();
  await expect(page.getByText("By ticket status")).toBeVisible();
  expect(await horizontalOverflow(page)).toBeLessThanOrEqual(0);
});

test("the theme choice survives a reload", async ({ page }) => {
  await openSignIn(page);
  await page.getByRole("button", { name: "Dark" }).click();
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});
