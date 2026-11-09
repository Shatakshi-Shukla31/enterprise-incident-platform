import { expect, test, type Page } from "@playwright/test";
import { exploreDemo } from "./helpers";

// A simulated microphone, so recording can be tested without a person speaking.
test.use({
  permissions: ["microphone"],
  launchOptions: { args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"] },
});

const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
  "base64",
);
const LOG = "10:01 INFO client starting\n10:02 ERROR VPN tunnel keeps disconnecting, gateway timed out\n";

async function openAssistant(page: Page) {
  await exploreDemo(page);
  await page.getByRole("link", { name: "Assistant", exact: true }).click();
  await expect(page.getByRole("button", { name: "New conversation" })).toBeVisible();
}

async function waitForUploads(page: Page, name: string) {
  const files = page.getByRole("list", { name: "Files to send" });
  await expect(files).toContainText(name);
  await expect(files).not.toContainText("Uploading");
}

async function send(page: Page, text: string) {
  const box = page.getByLabel("Message", { exact: true });
  await box.fill(text);
  const reply = page.waitForResponse((response) => response.url().includes("/ai/chat"));
  await box.press("Enter");
  expect((await reply).status()).toBe(200);
}

test("an attached log is read and helps find the answer", async ({ page }) => {
  await openAssistant(page);
  await page.locator('input[name="attachment"]').setInputFiles({ name: "vpn-client.log", mimeType: "text/plain", buffer: Buffer.from(LOG) });
  await waitForUploads(page, "vpn-client.log");
  await send(page, "this keeps happening every few minutes");
  await expect(page.locator("main")).toContainText("KB-1001");
  await expect(page.getByRole("button", { name: /vpn-client\.log/ })).toBeVisible();
});

test("a photo is shown in the conversation", async ({ page }) => {
  await openAssistant(page);
  await page.locator('input[name="photo"]').setInputFiles({ name: "screen.png", mimeType: "image/png", buffer: PNG });
  await waitForUploads(page, "screen.png");
  await send(page, "my laptop shows a black screen");
  await expect(page.getByRole("img", { name: "screen.png" })).toBeVisible();
});

test("a voice note can be recorded and sent", async ({ page }) => {
  await openAssistant(page);
  await page.getByRole("button", { name: "Record a voice note" }).click();
  await expect(page.getByRole("status")).toContainText("Recording");
  await page.waitForTimeout(1500);
  await page.getByRole("button", { name: "Stop recording" }).click();
  await waitForUploads(page, "voice-note");
  await send(page, "printer jobs stuck in the queue");
  await expect(page.getByLabel(/^Voice note voice-note/)).toBeVisible();
});

test("a file of the wrong type is refused", async ({ page }) => {
  await openAssistant(page);
  await page.locator('input[name="attachment"]').setInputFiles({ name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from([0xff, 0xfe, 0x00, 0x41]) });
  await expect(page.getByRole("list", { name: "Files to send" })).toContainText("Attach a photo, a voice note");
});
