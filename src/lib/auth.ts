/**
 * Account API client.
 *
 * Sessions are opaque bearer tokens issued by the backend. The token is kept in
 * localStorage so the SPA survives a reload; the backend stores only its hash.
 *
 * Nothing here decides entitlement. The server does, and its answer is passed
 * through `entitlementFromServer`, which fails closed.
 */

import { API_BASE_URL, TranscriptionError } from "./api";

const TOKEN_STORAGE_KEY = "captionline.session.token";

export type AuthUser = {
  id: number;
  email: string;
  plan: string;
  subscription_status: string;
  is_active: boolean;
  created_at: string;
};

export type AuthTokenResponse = {
  access_token: string;
  token_type: string;
  expires_at: string;
  user: AuthUser;
};

/** Mirrors `EntitlementResponse` on the backend. */
export type AccountEntitlement = {
  plan: string;
  plan_label: string;
  subscription_status: string;
  monthly_processing_allowance_seconds: number;
  processing_used_seconds: number;
  processing_remaining_seconds: number;
  usage_period_started_at: string;
  usage_period_ends_at: string;
  preview_limit_seconds: number | null;
  has_full_preview: boolean;
  can_export: boolean;
  processing_allowance_minutes: number;
  processing_used_minutes: number;
  processing_remaining_minutes: number;
};

export function getStoredToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    // Private browsing or blocked storage: treat as signed out.
    return null;
  }
}

export function storeToken(token: string | null): void {
  try {
    if (token === null) {
      window.localStorage.removeItem(TOKEN_STORAGE_KEY);
    } else {
      window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
    }
  } catch {
    // Storage unavailable; the session simply will not persist across reloads.
  }
}

async function postJson<T>(path: string, body: unknown, token?: string | null): Promise<T> {
  let response: Response;

  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(body),
    });
  } catch {
    throw new TranscriptionError(
      `Could not reach the Captionline service at ${API_BASE_URL}.`,
      0,
    );
  }

  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (typeof payload.detail === "string") {
        message = payload.detail;
      }
    } catch {
      // Keep the status-based message.
    }
    throw new TranscriptionError(message, response.status);
  }

  // 204 has no body.
  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

async function getJson<T>(path: string, token: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });

  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (typeof payload.detail === "string") {
        message = payload.detail;
      }
    } catch {
      // Keep the status-based message.
    }
    throw new TranscriptionError(message, response.status);
  }

  return (await response.json()) as T;
}

export function registerAccount(email: string, password: string): Promise<AuthTokenResponse> {
  return postJson<AuthTokenResponse>("/api/auth/register", { email, password });
}

export function loginAccount(email: string, password: string): Promise<AuthTokenResponse> {
  return postJson<AuthTokenResponse>("/api/auth/login", { email, password });
}

export function fetchCurrentUser(token: string): Promise<AuthUser> {
  return getJson<AuthUser>("/api/auth/me", token);
}

export function fetchEntitlement(token: string): Promise<AccountEntitlement> {
  return getJson<AccountEntitlement>("/api/account/entitlement", token);
}

export function logoutAccount(token: string): Promise<void> {
  return postJson<void>("/api/auth/logout", {}, token);
}
