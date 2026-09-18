import type {
  Notification,
  Overview,
  Paginated,
  Subscription,
  SubscriptionDetail,
} from "./types";

let csrfToken: string | null = null;

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const method = init?.method ?? "GET";
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");
  if (init?.body) headers.set("Content-Type", "application/json");
  if (method !== "GET" && method !== "HEAD") {
    if (csrfToken) headers.set("X-CSRF-Token", csrfToken);
  }
  const response = await fetch(`/api${path}`, {
    signal: AbortSignal.timeout(15_000),
    ...init,
    headers,
    credentials: "same-origin",
  });
  if (!response.ok) {
    if (response.status === 401) {
      csrfToken = null;
      queueMicrotask(() =>
        window.dispatchEvent(new Event("dashboard-auth-expired")),
      );
    }
    let message = "요청을 처리하지 못했습니다.";
    try {
      const body = (await response.json()) as {
        detail?: string;
        message?: string;
      };
      if (typeof body.detail === "string") message = body.detail;
      else if (typeof body.message === "string") message = body.message;
    } catch {
      // The response may not have a JSON body.
    }
    throw new ApiError(response.status, message);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function login(password: string): Promise<void> {
  const result = await request<{ csrf_token: string }>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ password }),
  });
  csrfToken = result.csrf_token;
}

export async function session(): Promise<boolean> {
  try {
    const result = await request<{ csrf_token: string }>("/auth/session");
    csrfToken = result.csrf_token;
    return true;
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      csrfToken = null;
      return false;
    }
    throw error;
  }
}

export async function logout(): Promise<void> {
  await request<void>("/auth/logout", { method: "POST" });
  csrfToken = null;
}

export const getOverview = () => request<Overview>("/overview");

export function getSubscriptions(params: Record<string, string | number>) {
  return request<Paginated<Subscription>>(
    `/subscriptions?${new URLSearchParams(stringParams(params))}`,
  );
}

export const getSubscription = (id: string) =>
  request<SubscriptionDetail>(`/subscriptions/${encodeURIComponent(id)}`);

export function deleteSubscription(id: string) {
  return request<void>(`/subscriptions/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export function getNotifications(params: Record<string, string | number>) {
  return request<Paginated<Notification>>(
    `/notifications?${new URLSearchParams(stringParams(params))}`,
  );
}

export const getNotification = (id: string) =>
  request<Notification>(`/notifications/${encodeURIComponent(id)}`);

export function retryNotification(id: string) {
  return request<void>(`/notifications/${encodeURIComponent(id)}/retry`, {
    method: "POST",
  });
}

function stringParams(
  params: Record<string, string | number>,
): Record<string, string> {
  return Object.fromEntries(
    Object.entries(params)
      .filter(([, value]) => value !== "")
      .map(([key, value]) => [key, String(value)]),
  );
}

export function clearSession() {
  csrfToken = null;
}
