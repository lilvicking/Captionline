/**
 * Minimal client-side routing.
 *
 * Captionline has no router dependency: the app is a small state machine. This
 * adds just enough to serve the one page that must have a real URL, because a
 * password reset link arrives by email and has to survive a page load.
 *
 * Only the two hardcoded paths below are ever navigated to. No user input
 * reaches `navigateTo`, so this cannot become an open redirect.
 */

import { useEffect, useState } from "react";

export const FORGOT_PASSWORD_PATH = "/forgot-password";
export const RESET_PASSWORD_PATH = "/reset-password";

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

/** Reads a query parameter from the current URL. */
export function readQueryParam(name: string): string {
  try {
    return new URLSearchParams(window.location.search).get(name) ?? "";
  } catch {
    return "";
  }
}
