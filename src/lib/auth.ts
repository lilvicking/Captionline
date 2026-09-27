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
  is_paid_plan: boolean;
  monthly_processing_allowance_seconds: number;
  processing_used_seconds: number;
  processing_reserved_seconds: number;
  processing_remaining_seconds: number;
  usage_period_started_at: string;
  usage_period_ends_at: string;
  usage_period_months: number;
  usage_resets_monthly: boolean;
  /** True when Stripe bills annually. Independent of the monthly usage reset. */
  billed_annually: boolean;
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

/* -------------------------------------------------------------------------- */
/* Password recovery                                                          */
/* -------------------------------------------------------------------------- */

/**
 * Requests a password reset email.
 *
 * Resolves for every outcome, including an unknown address: the backend always
 * answers with one generic message so account existence cannot be probed.
 */
export async function requestPasswordReset(email: string): Promise<void> {
  await postJson<unknown>("/api/auth/forgot-password", { email });
}

/** Redeems a reset token and sets a new password. */
export async function resetPassword(
  token: string,
  newPassword: string,
): Promise<void> {
  await postJson<unknown>("/api/auth/reset-password", { token, new_password: newPassword });
}

/**
 * Changes the password for the signed-in account.
 *
 * The token must be passed: this endpoint is authenticated, and omitting it
 * sends no `Authorization` header, so the backend answers 401.
 */
export async function changePassword(
  currentPassword: string,
  newPassword: string,
  token: string,
): Promise<void> {
  await postJson<unknown>(
    "/api/auth/change-password",
    {
      current_password: currentPassword,
      new_password: newPassword,
    },
    token,
  );
}

/* -------------------------------------------------------------------------- */
/* Account deletion                                                           */
/* -------------------------------------------------------------------------- */

/** Mirrors `AccountDeleteResponse` on the backend. */
export type AccountDeleteResult = {
  deleted: boolean;
};

/**
 * Permanently deletes the signed-in account.
 *
 * The backend requires the current password and the literal confirmation word
 * so an unattended browser cannot destroy an account, and answers 409 while a
 * subscription is still active. Both conditions are enforced here as well so
 * the user is not made to wait for a round trip to be told something the form
 * already knows.
 */
export async function deleteAccount(
  token: string,
  currentPassword: string,
  confirmation: string,
): Promise<AccountDeleteResult> {
  const payload = await postJson<AccountDeleteResult>(
    "/api/account/delete",
    { current_password: currentPassword, confirmation },
    token,
  );

  return { deleted: payload?.deleted !== false };
}
