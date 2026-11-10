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
    if (url.endsWith("/knowledge/search")) return json(200, [{ chunk_id: 1, title: "VPN disconnects", source_ref: "KB-1001", content: "Update the VPN client." }]);
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
  it("keeps attachment options in a plus menu that closes with Escape or an outside click", async () => {
    renderPage();
    const plus = screen.getByRole("button", { name: "Add attachments" });
    expect(plus).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    await userEvent.click(plus);
    expect(screen.getByRole("menuitem", { name: "Files" })).toBeEnabled();
    expect(screen.getByRole("menuitem", { name: "Add a photo" })).toBeEnabled();
    expect(screen.getByRole("menuitem", { name: "Record a voice note" })).toBeInTheDocument();
    expect(document.querySelector('input[name="photo"]')).toHaveAttribute("capture", "environment");
    await userEvent.keyboard("{ArrowDown}");
    expect(screen.getByRole("menuitem", { name: "Audio" })).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(plus).toHaveFocus();
    await userEvent.click(plus);
    await userEvent.click(screen.getByLabelText("Message"));
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("explains when this browser cannot record", async () => {
    renderPage();
    await userEvent.click(screen.getByRole("button", { name: "Add attachments" }));
    const mic = screen.getByRole("menuitem", { name: "Record a voice note" });
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
    await waitFor(() => expect(screen.getByRole("button", { name: "Add attachments" })).toBeDisabled());
  });

  it("formats sizes for people", () => {
    expect(formatSize(900)).toBe("900 B");
    expect(formatSize(2048)).toBe("2 KB");
    expect(formatSize(3 * 1024 * 1024)).toBe("3.0 MB");
  });

  it("offers named image, audio, video, PDF and file options", async () => {
    renderPage();
    await userEvent.click(screen.getByRole("button", { name: "Add attachments" }));
    for (const label of ["Image", "Audio", "Video", "PDF", "Files"]) {
      expect(screen.getByRole("menuitem", { name: label })).toBeEnabled();
    }
    expect(screen.getByText("Shatakshi Shukla")).toBeInTheDocument();
    expect(document.querySelector('input[name="video"]')).toHaveAttribute("accept", expect.stringContaining("video/mp4"));
  });

  it("sends video files through the category picker", async () => {
    renderPage();
    const input = document.querySelector<HTMLInputElement>('input[name="video"]')!;
    await userEvent.upload(input, new File(["video"], "recording.mp4", { type: "video/mp4" }));
    await waitFor(() => expect(screen.getByRole("list", { name: "Files to send" })).not.toHaveTextContent("Uploading"));
    await userEvent.type(screen.getByLabelText("Message"), "The screen freezes{Enter}");
    await waitFor(() => expect(chatBody().attachment_ids).toEqual([41]));
  });

  it("searches permitted knowledge and uses an article as a chat prompt", async () => {
    renderPage();
    await userEvent.click(screen.getByRole("button", { name: "Knowledge" }));
    await userEvent.type(screen.getByLabelText("Search assistant knowledge"), "vpn");
    await userEvent.click(screen.getByRole("button", { name: "Search knowledge" }));
    expect(await screen.findByText("Update the VPN client.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Ask about this" }));
    expect(screen.getByLabelText("Message")).toHaveValue("Help me with VPN disconnects");
  });

  it("restores a message and its files after a send failure", async () => {
    const original = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((url: string, init?: RequestInit) => url.endsWith("/ai/chat") ? Promise.resolve(json(503, { detail: "Please try again" })) : original(url, init));
    renderPage();
    await userEvent.upload(fileInput(), new File(["error"], "client.log", { type: "text/plain" }));
    await waitFor(() => expect(screen.getByRole("list", { name: "Files to send" })).not.toHaveTextContent("Uploading"));
    await userEvent.type(screen.getByLabelText("Message"), "my vpn drops");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Please try again");
    expect(screen.getByLabelText("Message")).toHaveValue("my vpn drops");
    expect(screen.getByRole("list", { name: "Files to send" })).toHaveTextContent("client.log");
  });
});
