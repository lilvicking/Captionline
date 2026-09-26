/**
 * Preview entitlement.
 *
 * ## What this is
 *
 * Phase 2 ships a free/unpaid preview tier: a user may work on their entire
 * project, but may only watch the first {@link FREE_PREVIEW_SECONDS} of the
 * finished captioned video. Everything else in the editor stays unrestricted.
 *
 * ## What this is NOT
 *
 * This is **UX-level preview protection only**. It is deliberately implemented
 * in the browser, which means it is *not* a security boundary: anyone can
 * disable it with devtools.
 *
 * Production entitlement **must** be decided server-side. When accounts and
 * billing arrive:
 *
 *   1. The backend determines entitlement from the authenticated account's
 *      subscription (e.g. Stripe) and returns it to the client.
 *   2. `resolvePreviewEntitlement()` is repointed at that server response.
 *   3. A paid account receives `hasFullPreview: true` (no preview limit); an
 *      unpaid account receives the {@link FREE_PREVIEW_SECONDS} window.
 *
 * The frontend must never be the component that decides whether someone paid.
 * Until that server endpoint exists, this module always resolves to the free
 * tier — there is deliberately no `isPaid = true` development flag that could
 * be flipped and accidentally shipped.
 *
 * Phase 3A adds `entitlementFromServer` so the signed-in entitlement can flow
 * in from `GET /api/account/entitlement`. It is written to **fail closed**: any
 * missing, malformed, or unexpected field yields the restrictive free tier, so
 * a bad response can never widen preview access.
 */

/** Length of the finished-video preview granted to unpaid users, in seconds. */
export const FREE_PREVIEW_SECONDS = 30;

/** Where the current entitlement came from. */
export type PreviewEntitlementSource = "free-tier" | "server";

export type PreviewEntitlement = {
  /**
   * Seconds of finished video the user may watch. `null` means unrestricted.
   * A future paid entitlement sets this to `null` alongside `hasFullPreview`.
   */
  previewLimitSeconds: number | null;
  /** True when the whole finished video may be previewed. */
  hasFullPreview: boolean;
  source: PreviewEntitlementSource;
};

/** The unpaid / free-tier entitlement applied as the default and fallback. */
export const FREE_PREVIEW_ENTITLEMENT: PreviewEntitlement = {
  previewLimitSeconds: FREE_PREVIEW_SECONDS,
  hasFullPreview: false,
  source: "free-tier",
};

/**
 * Resolves the entitlement to enforce for the current viewer.
 *
 * Defaults to the free tier, which is also what an anonymous visitor gets. This
 * remains the synchronous fallback; `entitlementFromServer` supplies the
 * authenticated value once an account is signed in.
 */
export function resolvePreviewEntitlement(): PreviewEntitlement {
  return FREE_PREVIEW_ENTITLEMENT;
}

/**
 * Converts `GET /api/account/entitlement` into a preview entitlement.
 *
 * Fails closed by design. An unrestricted preview is only honoured when the
 * server explicitly reports `hasFullPreview === true`; anything else, including
 * a null/missing limit, a non-numeric value, or a completely unexpected payload,
 * falls back to the free 30-second window.
 */
export function entitlementFromServer(payload: unknown): PreviewEntitlement {
  if (typeof payload !== "object" || payload === null) {
    return FREE_PREVIEW_ENTITLEMENT;
  }

  const record = payload as Record<string, unknown>;
  const serverSaysFullPreview = record.hasFullPreview === true;

  if (serverSaysFullPreview) {
    return {
      previewLimitSeconds: null,
      hasFullPreview: true,
      source: "server",
    };
  }

  const limit = record.previewLimitSeconds;

  // Only trust a limit the server actually sent as a usable number.
  if (typeof limit === "number" && Number.isFinite(limit) && limit >= 0) {
    return {
      previewLimitSeconds: limit,
      hasFullPreview: false,
      source: "server",
    };
  }

  return FREE_PREVIEW_ENTITLEMENT;
}

/**
 * Whether the finished video may be shown at `seconds`. Seeking up to and
 * including the boundary is allowed; the lock engages once playback reaches it.
 */
export function canPreviewAt(seconds: number, entitlement: PreviewEntitlement): boolean {
  if (entitlement.previewLimitSeconds === null || entitlement.hasFullPreview) {
    return true;
  }
  return seconds <= entitlement.previewLimitSeconds;
}

/** Whether playback has reached the preview boundary and must be stopped. */
export function hasReachedPreviewLimit(
  seconds: number,
  entitlement: PreviewEntitlement,
): boolean {
  if (entitlement.previewLimitSeconds === null || entitlement.hasFullPreview) {
    return false;
  }
  return seconds >= entitlement.previewLimitSeconds;
}
