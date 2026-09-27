/**
 * Configuration for the public legal pages.
 *
 * Two values have to be supplied by whoever launches Captionline, because the
 * frontend is the only place they are shown:
 *
 *   VITE_SUPPORT_EMAIL  the address the support page tells people to write to
 *   VITE_GOVERNING_LAW  the law and forum the Terms are governed by
 *
 * Both are optional at build time. When one is missing the page says so in
 * plain language rather than printing a placeholder address, an unowned
 * mailbox, or an invented jurisdiction: a legal page that quietly guesses is
 * worse than one that admits the clause is not settled yet.
 */

const configuredSupportEmail = import.meta.env.VITE_SUPPORT_EMAIL?.trim();
const configuredGoverningLaw = import.meta.env.VITE_GOVERNING_LAW?.trim();

/** The support address, or null when the environment has not set one. */
export const SUPPORT_EMAIL: string | null =
  configuredSupportEmail && configuredSupportEmail.length > 0 ? configuredSupportEmail : null;

/** The governing law and forum, or null when the environment has not set one. */
export const GOVERNING_LAW: string | null =
  configuredGoverningLaw && configuredGoverningLaw.length > 0 ? configuredGoverningLaw : null;

/**
 * Shown in place of the governing-law clause until VITE_GOVERNING_LAW is set.
 *
 * It is worded as a visible gap rather than as a law claim, so nobody reading
 * the page can mistake it for a real jurisdiction.
 */
export const GOVERNING_LAW_PENDING =
  "Captionline has not published a governing law and forum yet. That clause is added before " +
  "this service takes paid subscriptions; until it is, the law that applies to your use of " +
  "Captionline is not stated on this page.";

/** Shown instead of a support address when VITE_SUPPORT_EMAIL is not set. */
export const SUPPORT_EMAIL_PENDING =
  "Email support is not yet available. Please check back soon.";

/** A `mailto:` link is only offered when an address is actually configured. */
export function supportMailto(): string | null {
  return SUPPORT_EMAIL ? `mailto:${SUPPORT_EMAIL}` : null;
}
