/**
 * Billing client.
 *
 * The frontend never decides what a plan costs or what it grants. It names an
 * internal plan id, the backend maps that to a Stripe Price, and entitlement
 * only changes once Stripe's webhook has been verified server-side.
 */

import { API_BASE_URL, TranscriptionError } from "./api";

export type Plan = {
  id: string;
  label: string;
  /** Billing cadence. */
  price_usd: number;
  billing_period: "monthly" | "annual";
  /** What this plan would cost per month on monthly billing. */
  monthly_equivalent_price_usd: number;
  /** Saving per year versus monthly billing. 0 when there is none. */
  annual_savings_usd: number;
  /** Usage cadence, independent of billing cadence. */
  usage_allowance_seconds: number;
  usage_period_months: number;
  usage_resets_monthly: boolean;
  preview_limit_seconds: number | null;
  has_full_preview: boolean;
  can_export: boolean;
  tagline: string;
  is_current: boolean;
  /** False when Stripe is not configured for this plan on the backend. */
  purchasable: boolean;
};

async function readError(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (typeof payload.detail === "string") {
      return payload.detail;
    }
  } catch {
    // Fall through to the status text.
  }
  return response.statusText || `Request failed with status ${response.status}`;
}

function billingUrl(path: string): string {
  return `${API_BASE_URL}${path}`;
}

/**
 * Fetches the authoritative plan catalogue.
 *
 * Returns an empty array on failure so the pricing section can fall back to a
 * plain message rather than rendering incorrect prices or crashing the page.
 */
export async function fetchPlans(token: string | null): Promise<Plan[]> {
  try {
    const response = await fetch(billingUrl("/api/account/plans"), {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });

    if (!response.ok) {
      return [];
    }

    const payload = (await response.json()) as Plan[];
    return Array.isArray(payload) ? payload : [];
  } catch {
    return [];
  }
}

/** Starts a Stripe Checkout session and returns the hosted checkout URL. */
export async function startCheckout(plan: string, token: string): Promise<string> {
  const response = await fetch(billingUrl("/api/billing/checkout"), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ plan }),
  });

  if (!response.ok) {
    throw new TranscriptionError(await readError(response), response.status);
  }

  const payload = (await response.json()) as { url: string };
  return payload.url;
}

/** Opens the Stripe Customer Portal for managing an existing subscription. */
export async function openBillingPortal(token: string): Promise<string> {
  const response = await fetch(billingUrl("/api/billing/portal"), {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });

  if (!response.ok) {
    throw new TranscriptionError(await readError(response), response.status);
  }

  const payload = (await response.json()) as { url: string };
  return payload.url;
}

/** Formats a plan price for display, e.g. "$19/month" or "$149/year". */
export function formatPrice(plan: Plan): string {
  if (plan.price_usd === 0) {
    return "$0";
  }
  return plan.billing_period === "annual" ? `$${plan.price_usd}/year` : `$${plan.price_usd}/month`;
}

/** Formats a processing allowance, always as a per-month figure. */
export function formatAllowance(plan: Plan): string {
  const minutes = plan.usage_allowance_seconds / 60;
  const amount = minutes >= 100 ? `${Math.round(minutes).toLocaleString()}` : `${minutes}`;

  return plan.usage_resets_monthly
    ? `${amount} processing minutes a month`
    : `${amount} processing minutes`;
}
