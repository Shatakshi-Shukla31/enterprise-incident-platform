import { expect, test } from "@playwright/test";
import { exploreDemo, horizontalOverflow } from "./helpers";

test.beforeEach(async ({ page }) => {
  await exploreDemo(page);
  await page.getByRole("link", { name: "Assistant", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Support assistant", exact: true })).toBeVisible();
});

test("greetings and owner questions work and persist in conversation history", async ({ page }) => {
  const message = page.getByLabel("Message", { exact: true });
  await message.fill("hi");
  await message.press("Enter");
  await expect(page.getByText("Hi! I'm the Incident Platform support assistant.", { exact: false })).toBeVisible();
  await message.fill("how is your oewner ?");
  await message.press("Enter");
  await expect(page.getByText("The owner of Incident Platform is Shatakshi Shukla.", { exact: false })).toBeVisible();
  await page.screenshot({ path: "test-results/assistant-desktop.png", fullPage: true });
  await page.reload();
  await page.getByRole("list", { name: "Conversations" }).getByRole("button", { name: "hi", exact: true }).first().click();
  await expect(page.getByText("The owner of Incident Platform is Shatakshi Shukla.", { exact: false })).toBeVisible();
});

test("knowledge can be searched and an article can become a chat question", async ({ page }) => {
  await page.getByRole("button", { name: "Knowledge", exact: true }).click();
  await page.getByLabel("Search assistant knowledge").fill("Shatakshi Shukla owner");
  await page.getByRole("button", { name: "Search knowledge" }).click();
  await expect(page.getByRole("region", { name: "Assistant knowledge" })).toContainText("KB-1000");
  await page.getByRole("button", { name: "Ask about this" }).first().click();
  await expect(page.getByLabel("Message", { exact: true })).toHaveValue(/Help me with/);
});

test("video uploads remain attached after reloading", async ({ page }) => {
  await page.locator('input[name="video"]').setInputFiles({
    name: "screen-recording.mp4",
    mimeType: "video/mp4",
    buffer: Buffer.concat([Buffer.from([0, 0, 0, 24]), Buffer.from("ftypisom"), Buffer.alloc(64)]),
  });
  await expect(page.getByRole("list", { name: "Files to send" })).toContainText("screen-recording.mp4");
  await expect(page.getByRole("list", { name: "Files to send" })).not.toContainText("Uploading");
  await page.getByLabel("Message", { exact: true }).fill("My screen freezes during a video call");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(page.getByLabel("Video screen-recording.mp4")).toBeVisible();
  await page.reload();
  await page.getByRole("list", { name: "Conversations" }).getByRole("button", { name: "My screen freezes during a video call", exact: true }).first().click();
  await expect(page.getByLabel("Video screen-recording.mp4")).toBeVisible();
});

test("attachment controls fit on a phone", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const plus = page.getByRole("button", { name: "Add attachments", exact: true });
  await expect(page.getByRole("menu")).toHaveCount(0);
  await plus.click();
  for (const name of ["Image", "Audio", "Video", "PDF", "Files"]) {
    await expect(page.getByRole("menuitem", { name, exact: true })).toBeVisible();
  }
  expect(await horizontalOverflow(page)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: "test-results/assistant-phone.png", fullPage: true });
  await page.keyboard.press("Escape");
  await expect(page.getByRole("menu")).toHaveCount(0);
  await expect(plus).toBeFocused();
  await page.setViewportSize({ width: 1280, height: 900 });
  await plus.click();
  await page.screenshot({ path: "test-results/assistant-menu-light.png", fullPage: true });
  await page.getByLabel("Message", { exact: true }).click();
  await expect(page.getByRole("menu")).toHaveCount(0);
  await page.getByRole("button", { name: "Dark", exact: true }).click();
  await plus.click();
  await page.screenshot({ path: "test-results/assistant-menu-dark.png", fullPage: true });
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("menuitem", { name: "PDF", exact: true }).click();
  await (await chooser).setFiles({ name: "test.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.7\n") });
  await expect(page.getByRole("menu")).toHaveCount(0);
  await expect(page.getByRole("list", { name: "Files to send" })).toContainText("test.pdf");
});
