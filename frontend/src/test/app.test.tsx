import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { App } from "../App";
import { AuthProvider } from "../auth/AuthContext";
import { setAccessToken } from "../lib/api";

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const requester = { id: 5, email: "user@test.io", full_name: "Uma User", role: "requester", team_id: null, is_active: true };
const manager = { ...requester, full_name: "Mohan Manager", role: "manager" };
const emptyPage = { items: [], total: 0, page: 1, page_size: 20 };
const noNotifications = { total: 0, unread: 0, by_type: [], by_status: [] };
const someNotifications = {
  total: 3,
  unread: 2,
  by_type: [
    { key: "comment", unread: 0, read: 1 },
    { key: "sla_breach", unread: 2, read: 0 },
  ],
  by_status: [
    { key: "new", unread: 2, read: 0 },
    { key: "closed", unread: 0, read: 1 },
  ],
};
const breach = { id: 1, incident_id: 9, type: "sla_breach", title: "SLA breached: INC0000009", body: "Passed its target.", created_at: "2026-01-01T10:00:00Z", read_at: null };

function stubServer(user: typeof requester, loggedIn = true, notifications: { list?: unknown[]; summary?: Response } = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url.endsWith("/auth/refresh")) return loggedIn ? json(200, { access_token: "t" }) : json(401, { detail: "none" });
      if (url.endsWith("/auth/login") || url.endsWith("/auth/register")) return json(200, { access_token: "t" });
      if (url.endsWith("/auth/logout")) return new Response(null, { status: 204 });
      if (url.endsWith("/auth/me")) return json(200, user);
      if (url.includes("/notifications/summary")) return notifications.summary ?? json(200, noNotifications);
      if (url.includes("/notifications")) return json(200, notifications.list ?? []);
      if (url.includes("/incidents")) return json(200, emptyPage);
      if (url.includes("/teams")) return json(200, []);
      return json(404, { detail: "unexpected" });
    }),
  );
}

function renderApp(path = "/") {
  setAccessToken(null);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <MemoryRouter initialEntries={[path]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
          <App />
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

describe("App", () => {
  it("shows the login form without a session", async () => {
    stubServer(requester, false);
    renderApp();
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
  });

  it("signs in and opens the incident list", async () => {
    stubServer(requester, false);
    renderApp();
    await userEvent.type(await screen.findByLabelText("Email"), "user@test.io");
    await userEvent.type(screen.getByLabelText("Password"), "correct-horse-battery");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "Incidents" })).toBeInTheDocument();
  });

  it("hides staff navigation from requesters", async () => {
    stubServer(requester);
    renderApp();
    await screen.findByRole("heading", { name: "Incidents" });
    expect(screen.queryByRole("link", { name: "Dashboard" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Knowledge" })).not.toBeInTheDocument();
  });

  it("redirects a requester away from the dashboard route", async () => {
    stubServer(requester);
    renderApp("/dashboard");
    expect(await screen.findByRole("heading", { name: "Incidents" })).toBeInTheDocument();
  });

  it("shows the dashboard link to managers", async () => {
    stubServer(manager);
    renderApp();
    expect(await screen.findByRole("link", { name: "Dashboard" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("link", { name: "Approvals" })).toBeInTheDocument());
  });

  it("offers the theme switch next to the account", async () => {
    stubServer(requester);
    renderApp();
    expect(await screen.findByRole("group", { name: "Colour theme" })).toBeInTheDocument();
  });
});

describe("Sign-in page", () => {
  const registerCall = () => vi.mocked(fetch).mock.calls.find(([url]) => String(url).endsWith("/auth/register"));

  async function openCreateAccount(audience: RegExp) {
    stubServer(requester, false);
    renderApp();
    await userEvent.click(await screen.findByRole("radio", { name: audience }));
    await userEvent.click(screen.getByRole("radio", { name: "Create account" }));
  }

  async function fillAccount(confirm = "a-long-enough-password") {
    await userEvent.type(screen.getByLabelText("Full name"), "Shatakshi Shukla");
    await userEvent.type(screen.getByLabelText("Email"), "new@test.io");
    await userEvent.type(screen.getByLabelText(/^Password/), "a-long-enough-password");
    await userEvent.type(screen.getByLabelText("Confirm password"), confirm);
  }

  it("offers both account types and both actions", async () => {
    stubServer(requester, false);
    renderApp();
    expect(await screen.findByRole("radio", { name: /^User/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /^Admin/ })).not.toBeChecked();
    expect(screen.getByRole("radio", { name: "Sign in" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "Create account" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Colour theme" })).toBeInTheDocument();
  });

  it("creates a user account and opens the app", async () => {
    await openCreateAccount(/^User/);
    expect(screen.queryByLabelText(/^Admin access code/)).not.toBeInTheDocument();
    await fillAccount();
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByRole("heading", { name: "Incidents" })).toBeInTheDocument();
    expect(JSON.parse(String(registerCall()?.[1]?.body))).toEqual({ email: "new@test.io", full_name: "Shatakshi Shukla", password: "a-long-enough-password" });
  });

  it("sends the access code for an admin account", async () => {
    await openCreateAccount(/^Admin/);
    await fillAccount();
    await userEvent.type(screen.getByLabelText(/^Admin access code/), "the-secret-code");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    await screen.findByRole("heading", { name: "Incidents" });
    expect(JSON.parse(String(registerCall()?.[1]?.body)).admin_code).toBe("the-secret-code");
  });

  it("stops before sending when the passwords differ", async () => {
    await openCreateAccount(/^User/);
    await fillAccount("something-else-entirely");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("do not match");
    expect(registerCall()).toBeUndefined();
  });

  it("keeps a requester out of the admin sign-in", async () => {
    stubServer(requester, false);
    renderApp();
    await userEvent.click(await screen.findByRole("radio", { name: /^Admin/ }));
    await userEvent.type(screen.getByLabelText("Email"), "user@test.io");
    await userEvent.type(screen.getByLabelText("Password"), "correct-horse-battery");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("no staff access");
    expect(screen.queryByRole("heading", { name: "Incidents" })).not.toBeInTheDocument();
  });

  it("lets staff use the admin sign-in", async () => {
    stubServer(manager, false);
    renderApp();
    await userEvent.click(await screen.findByRole("radio", { name: /^Admin/ }));
    await userEvent.type(screen.getByLabelText("Email"), "manager@test.io");
    await userEvent.type(screen.getByLabelText("Password"), "correct-horse-battery");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "Incidents" })).toBeInTheDocument();
  });

  it("reveals the password on request", async () => {
    stubServer(requester, false);
    renderApp();
    const field = await screen.findByLabelText("Password");
    expect(field).toHaveAttribute("type", "password");
    await userEvent.click(screen.getByRole("button", { name: "Show password" }));
    expect(field).toHaveAttribute("type", "text");
  });
});

describe("Notifications page", () => {
  it("charts every row of the summary above the list", async () => {
    stubServer(requester, true, { list: [breach], summary: json(200, someNotifications) });
    renderApp("/notifications");
    expect(await screen.findByRole("img", { name: "SLA breached: 2 unread, 0 read" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Closed: 0 unread, 1 read" })).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "SLA breached: INC0000009" })).toBeInTheDocument();
    expect(screen.getByText("Of 3 in total")).toBeInTheDocument();
  });

  it("shows an empty message and no chart when there is nothing", async () => {
    stubServer(requester);
    renderApp("/notifications");
    expect(await screen.findByText("Nothing here yet.")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Notifications by type" })).not.toBeInTheDocument();
  });

  it("keeps the list when the summary fails", async () => {
    stubServer(requester, true, { list: [breach], summary: json(500, { detail: "Summary unavailable" }) });
    renderApp("/notifications");
    expect(await screen.findByRole("link", { name: "SLA breached: INC0000009" })).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent("Summary unavailable");
    expect(screen.getByRole("button", { name: "Mark all read" })).toBeEnabled();
  });

  it("disables mark all read once everything is read", async () => {
    stubServer(requester, true, { list: [{ ...breach, read_at: "2026-01-02T10:00:00Z" }], summary: json(200, { ...someNotifications, unread: 0 }) });
    renderApp("/notifications");
    await screen.findByText("Of 3 in total");
    expect(screen.getByRole("button", { name: "Mark all read" })).toBeDisabled();
  });
});
