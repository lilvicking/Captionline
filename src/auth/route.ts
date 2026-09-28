/**
 * Minimal client-side routing.
 *
 * Captionline has no router dependency: the app is a small state machine. This
 * adds just enough to serve the pages that must have a real URL, because a
 * password reset link arrives by email and has to survive a page load, and the
 * legal pages have to be linkable and indexable.
 *
 * Only the hardcoded paths below are ever navigated to. No user input reaches
 * `navigateTo`, so this cannot become an open redirect.
 */

import { useEffect, useState } from "react";

export const HOME_PATH = "/";
export const FORGOT_PASSWORD_PATH = "/forgot-password";
export const RESET_PASSWORD_PATH = "/reset-password";
export const TERMS_PATH = "/terms";
export const PRIVACY_PATH = "/privacy";
export const CONTACT_PATH = "/contact";
/** The search-facing landing page. Indexed, and linked from the footer and nav. */
export const CAPTION_GENERATOR_PATH = "/caption-generator";
/**
 * Pricing lives as a section on the landing page, but it is advertised in the
 * sitemap, so it needs a real URL that lands on the plans rather than the
 * not-found page.
 */
export const PRICING_PATH = "/pricing";
/**
 * The support console. It has no entry point anywhere in the customer
 * interface: not in the navigation, not in the footer, and not in the Account
 * sheet. An administrator reaches it by typing this path directly.
 *
 * The route still renders for anyone who arrives at it; every admin endpoint
 * independently requires administrator status, so the console is empty of
 * anything useful unless the server agrees the caller is an administrator.
 */
export const ADMIN_PATH = "/admin";

/** Event used to notify the app that an in-app navigation happened. */
const NAVIGATE_EVENT = "captionline:navigate";

function currentPath(): string {
  const path = window.location.pathname.replace(/\/+$/, "");
  return path === "" ? "/" : path;
}

export function usePathname(): string {
  const [path, setPath] = useState(currentPath);

  useEffect(() => {
    const sync = () => setPath(currentPath());

    // popstate covers the browser back/forward buttons.
    window.addEventListener("popstate", sync);
    window.addEventListener(NAVIGATE_EVENT, sync);

    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener(NAVIGATE_EVENT, sync);
    };
  }, []);

  return path;
}

/** Navigate to an internal path. Callers pass constants only. */
export function navigateTo(path: string): void {
  if (currentPath() === path) {
    return;
  }

  window.history.pushState({}, "", path);
  window.dispatchEvent(new Event(NAVIGATE_EVENT));
}

/**
 * Rewrites the address bar without notifying the app.
 *
 * Used to drop a spent one-time token from the URL: the page must stay mounted
 * so its own confirmation is what the user sees, and a navigation would unmount
 * it. Back/forward is not rewritten either, so the spent link cannot be
 * replayed with the browser buttons.
 */
export function replaceUrlSilently(path: string): void {
  window.history.replaceState({}, "", path);
}

/** Long enough for React to have committed the next page before scrolling. */
const SCROLL_DELAY_MS = 80;

/**
 * Navigates in-app and, when the target names an anchor, scrolls to it once the
 * target page is on screen.
 *
 * Needed because the destination section often does not exist on the page being
 * left: the pricing section only exists on the landing page.
 */
export function navigateToAnchor(path: string, anchor: string): void {
  navigateTo(path);

  window.setTimeout(() => {
    document.getElementById(anchor)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, SCROLL_DELAY_MS);
}

/** Reads a query parameter from the current URL. */
export function readQueryParam(name: string): string {
  try {
    return new URLSearchParams(window.location.search).get(name) ?? "";
  } catch {
    return "";
  }
}
