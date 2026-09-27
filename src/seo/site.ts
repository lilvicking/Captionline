/**
 * Public site configuration.
 *
 * The canonical origin is the one place a domain is written down, so metadata,
 * canonical URLs, the sitemap and structured data all agree and none of them can
 * drift. Overridable for local builds via VITE_SITE_URL.
 */

const configured = import.meta.env.VITE_SITE_URL?.trim();

export const SITE_URL = (configured || "https://captionline.pro").replace(/\/+$/, "");

export const SITE_NAME = "Captionline";

/** Public routes worth indexing, in the order a crawler should meet them. */
export const PUBLIC_ROUTES = [
  { path: "/", priority: 1.0, changefreq: "weekly" as const },
  { path: "/caption-generator", priority: 0.9, changefreq: "monthly" as const },
  { path: "/pricing", priority: 0.7, changefreq: "monthly" as const },
  { path: "/contact", priority: 0.4, changefreq: "yearly" as const },
  { path: "/privacy", priority: 0.3, changefreq: "yearly" as const },
  { path: "/terms", priority: 0.3, changefreq: "yearly" as const },
];

/**
 * Routes that must never be indexed: they are account state, the support
 * console, or a single-use credential page. A crawler reaching them has nothing
 * to index and a reset link should not circulate.
 */
export const PRIVATE_ROUTES = ["/admin", "/reset-password", "/forgot-password"];

export function absoluteUrl(path: string): string {
  // The site root is canonically the origin with a trailing slash, so the
  // prerendered HTML, the client-side tags, and the canonical link all agree.
  if (path === "/" || path === "") {
    return `${SITE_URL}/`;
  }

  return `${SITE_URL}${path.replace(/\/+$/, "")}`;
}
