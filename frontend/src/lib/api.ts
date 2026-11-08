const BASE = "/api/v1";

// Held in memory only. The refresh token lives in an httpOnly cookie that scripts cannot read.
let accessToken: string | null = null;
let refreshing: Promise<boolean> | null = null;
let onSessionLost: () => void = () => {};

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function setSessionLostHandler(handler: () => void): void {
  onSessionLost = handler;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

function errorMessage(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg);
  if (status === 429) return "Too many requests. Please wait a moment.";
  return `Request failed (${status})`;
}

// One refresh at a time: concurrent 401s must not each spend the rotating token, because
// a second use of the same token is treated as theft and ends the session.
export function refreshSession(): Promise<boolean> {
  refreshing ??= fetch(`${BASE}/auth/refresh`, { method: "POST", credentials: "same-origin" })
    .then(async (response) => {
      if (!response.ok) return false;
      accessToken = (await response.json()).access_token;
      return true;
    })
    .catch(() => false)
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

async function send(path: string, init: RequestInit): Promise<Response> {
  const headers = new Headers(init.headers);
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  return fetch(`${BASE}${path}`, { ...init, headers, credentials: "same-origin" });
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response = await send(path, init);
  if (response.status === 401 && !path.startsWith("/auth/")) {
    if (await refreshSession()) {
      response = await send(path, init);
    } else {
      onSessionLost();
    }
  }
  if (response.status === 204) return undefined as T;
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, errorMessage(response.status, body));
  return body as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "POST",
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};

export async function login(email: string, password: string): Promise<void> {
  const body = await request<{ access_token: string }>("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ username: email, password }),
  });
  accessToken = body.access_token;
}

export interface Registration {
  email: string;
  full_name: string;
  password: string;
  admin_code?: string;
}

export async function register(details: Registration): Promise<void> {
  const body = await api.post<{ access_token: string }>("/auth/register", details);
  accessToken = body.access_token;
}

export async function demoLogin(): Promise<void> {
  const body = await api.post<{ access_token: string }>("/auth/demo");
  accessToken = body.access_token;
}

export async function logout(): Promise<void> {
  await api.post("/auth/logout").catch(() => undefined);
  accessToken = null;
}
