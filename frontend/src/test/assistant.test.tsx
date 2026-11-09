import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { formatSize } from "../components/Attachments";
import { AssistantPage } from "../pages/Assistant";

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const answer = {
  recommendation_id: 1,
  conversation_id: 7,
  answer: "Based on the retrieved sources:\n- Update the client. [S1]",
  citations: [{ id: "S1", document_id: 1, chunk_id: 1, title: "VPN", source_type: "kb_article", source_ref: "KB-1001", similarity: 0.7, excerpt: "Update" }],
  insufficient_evidence: false,
  provider: "extractive",
  latency_ms: 10,
  related_incidents: [],
  suggested_actions: [],
};

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  let nextId = 40;
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/ai/conversations")) return json(200, []);
    if (url.endsWith("/ai/attachments") && init?.method === "POST") {
      const file = (init.body as FormData).get("file") as File;
      return json(201, { id: (nextId += 1), kind: "text", filename: file.name, content_type: "text/plain", size_bytes: file.size });
    }
    if (url.endsWith("/ai/chat")) return json(200, answer);
    return json(404, { detail: "unexpected" });
  });
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:local"), revokeObjectURL: vi.fn() }));
});

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <AssistantPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const fileInput = () => document.querySelector<HTMLInputElement>('input[name="attachment"]')!;
const chatBody = () => JSON.parse(String(fetchMock.mock.calls.find(([url]) => String(url).endsWith("/ai/chat"))?.[1]?.body));

describe("Assistant attachments", () => {
  it("offers a file, a photo and a voice note beside the message box", () => {
    renderPage();
    expect(screen.getByRole("button", { name: "Attach a file" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Add a photo" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Record a voice note" })).toBeInTheDocument();
    expect(document.querySelector('input[name="photo"]')).toHaveAttribute("capture", "environment");
  });

  it("explains when this browser cannot record", () => {
    renderPage();
    const mic = screen.getByRole("button", { name: "Record a voice note" });
    expect(mic).toBeDisabled();
    expect(mic).toHaveAttribute("title", "This browser cannot record audio");
  });

  it("uploads a chosen file, shows it, and sends it with the message", async () => {
    renderPage();
    await userEvent.upload(fileInput(), new File(["ERROR tunnel timed out"], "client.log", { type: "text/plain" }));
    const chip = await screen.findByRole("list", { name: "Files to send" });
    await waitFor(() => expect(chip).toHaveTextContent("client.log"));
    await waitFor(() => expect(chip).not.toHaveTextContent("Uploading"));

    await userEvent.type(screen.getByLabelText("Message"), "my vpn drops");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("KB-1001", { exact: false })).toBeInTheDocument();
    expect(chatBody().attachment_ids).toEqual([41]);
    expect(screen.queryByRole("list", { name: "Files to send" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /client\.log/ })).toBeInTheDocument();
  });

  it("lets a file be removed before sending", async () => {
    renderPage();
    await userEvent.upload(fileInput(), new File(["x"], "wrong.txt", { type: "text/plain" }));
    await userEvent.click(await screen.findByRole("button", { name: "Remove wrong.txt" }));
    expect(screen.queryByRole("list", { name: "Files to send" })).not.toBeInTheDocument();
  });

  it("refuses a file over 5 MB without uploading it", async () => {
    renderPage();
    const big = new File([new Uint8Array(5 * 1024 * 1024 + 1)], "huge.log", { type: "text/plain" });
    await userEvent.upload(fileInput(), big);
    expect(await screen.findByText("Files can be up to 5 MB")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/ai/attachments"))).toBe(false);
  });

  it("stops accepting files at three", async () => {
    renderPage();
    await userEvent.upload(fileInput(), [1, 2, 3].map((n) => new File(["x"], `${n}.log`, { type: "text/plain" })));
    await waitFor(() => expect(screen.getByRole("button", { name: "Attach a file" })).toBeDisabled());
    expect(screen.getByRole("button", { name: "Add a photo" })).toBeDisabled();
  });

  it("formats sizes for people", () => {
    expect(formatSize(900)).toBe("900 B");
    expect(formatSize(2048)).toBe("2 KB");
    expect(formatSize(3 * 1024 * 1024)).toBe("3.0 MB");
  });
});
