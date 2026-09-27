/**
 * Administrative support console client.
 *
 * Every call here is admin-guarded on the server. Nothing in this module is a
 * security boundary: the browser can be asked to show the console at any time,
 * and the server will still refuse a non-administrator.
 */

import { API_BASE_URL, TranscriptionError } from "./api";

export type AdminUserSummary = {
  id: number;
  email: string;
  plan: string;
  subscription_status: string;
  is_active: boolean;
  is_admin: boolean;
  created_at: string;
  bonus_processing_seconds: number;
};

export type AdminUserDetail = AdminUserSummary & {
  plan_label: string;
  is_paid_plan: boolean;
  updated_at: string;
  monthly_processing_allowance_seconds: number;
  processing_used_seconds: number;
  processing_reserved_seconds: number;
  bonus_processing_seconds: number;
  processing_remaining_seconds: number;
  usage_period_started_at: string;
  usage_period_ends_at: string;
  usage_resets_monthly: boolean;
  billed_annually: boolean;
  has_full_preview: boolean;
  can_export: boolean;
  processing_allowance_minutes: number;
  processing_used_minutes: number;
  processing_remaining_minutes: number;
  terms_accepted_at: string | null;
  privacy_acknowledged_at: string | null;
};

export type AdminAuditEntry = {
  id: number;
  action: string;
  amount_seconds: number;
  reason: string;
  created_at: string;
  admin_user_id: number;
  admin_email: string;
};

export type AdminSummary = {
  total_users: number;
  free_users: number;
  paid_users: number;
  users_with_credit: number;
  total_bonus_seconds: number;
};

export function getToken(): string {
  return window.localStorage.getItem("captionline.session.token") ?? "";
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;

  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${getToken()}`,
        ...(init.headers ?? {}),
      },
    });
  } catch {
    throw new TranscriptionError("Could not reach the support service.", 0);
  }

  if (!response.ok) {
    let message = "The support console request failed.";

    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (typeof payload.detail === "string" && payload.detail.length < 300) {
        message = payload.detail;
      }
    } catch {
      // Keep the generic message.
    }

    throw new TranscriptionError(message, response.status);
  }

  return (await response.json()) as T;
}

export function fetchAdminSummary(): Promise<AdminSummary> {
  return request<AdminSummary>("/api/admin/summary");
}

export function searchCustomers(query: string): Promise<AdminUserSummary[]> {
  const trimmed = query.trim();
  return request<AdminUserSummary[]>(
    `/api/admin/users?q=${encodeURIComponent(trimmed)}`,
  );
}

export function fetchCustomer(id: number): Promise<AdminUserDetail> {
  return request<AdminUserDetail>(`/api/admin/users/${id}`);
}

/** Grants (positive minutes) or removes (negative minutes) support credit. */
export function adjustCredit(
  id: number,
  minutes: number,
  reason: string,
): Promise<AdminUserDetail> {
  return request<AdminUserDetail>(`/api/admin/users/${id}/credits`, {
    method: "POST",
    body: JSON.stringify({ minutes, reason }),
  });
}

export function fetchAudit(id: number): Promise<AdminAuditEntry[]> {
  return request<AdminAuditEntry[]>(`/api/admin/users/${id}/audit`);
}

/** Human label for an audit action. */
export function auditActionLabel(action: string): string {
  switch (action) {
    case "credit_granted":
      return "Credit granted";
    case "credit_removed":
      return "Credit removed";
    case "privilege_changed":
      return "Privilege changed";
    default:
      return action;
  }
}
