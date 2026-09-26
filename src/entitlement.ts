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
 * disable it with devtools, and the original uploaded media never leaves the
 * user's own machine in the first place.
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

/** The unpaid / free-tier entitlement applied throughout Phase 2. */
export const FREE_PREVIEW_ENTITLEMENT: PreviewEntitlement = {
  previewLimitSeconds: FREE_PREVIEW_SECONDS,
  hasFullPreview: false,
  source: "free-tier",
};

/**
 * Resolves the entitlement to enforce for the current viewer.
 *
 * Phase 2 always returns the free tier. This is the single seam to replace when
 * the backend starts reporting real subscription state.
 */
export function resolvePreviewEntitlement(): PreviewEntitlement {
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
