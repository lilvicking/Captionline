/**
 * Per-route document metadata and JSON-LD.
 *
 * The app renders on the client, so a route change is the moment to describe the
 * document. Everything is written through the DOM rather than templated, which
 * keeps it in step with whichever route is actually on screen.
 *
 * Only truthful values are emitted. There are no ratings, review counts, user
 * numbers, awards, or founding details, because Captionline has none, and a claim
 * that cannot be substantiated is worse for a product than no claim at all.
 */

import { useEffect } from "react";
import { absoluteUrl, SITE_NAME } from "./site";
import routeData from "./routes.json";

/**
 * Per-route metadata, read from the same JSON the post-build prerender script
 * consumes, so the served HTML and the client-updated tags cannot drift.
 */
const PUBLIC_ROUTES = routeData.routes as Record<
  string,
  { title: string; description: string; index: boolean }
>;

export type PageMeta = {
  /** Defaults to the shared entry for this path when omitted. */
  title?: string;
  description?: string;
  path: string;
  /** JSON-LD documents to attach to the page. */
  structuredData?: Record<string, unknown>[];
  /** Defaults to indexing. Set false for private or single-use routes. */
  index?: boolean;
};

/** Resolves the shared metadata for a path, if it is a public route. */
export function publicRouteMeta(path: string) {
  return PUBLIC_ROUTES[path] ?? null;
}

export const OG_IMAGE_PATH = routeData.ogImage;

const OG_IMAGE_ALT =
  "Captionline — automatic video captions, then edit, style and export.";

function setMeta(selector: string, attribute: "name" | "property", key: string, content: string) {
  let element = document.head.querySelector<HTMLMetaElement>(selector);

  if (!element) {
    element = document.createElement("meta");
    element.setAttribute(attribute, key);
    document.head.appendChild(element);
  }

  element.setAttribute("content", content);
}

function setCanonical(href: string) {
  let element = document.head.querySelector<HTMLLinkElement>('link[rel="canonical"]');

  if (!element) {
    element = document.createElement("link");
    element.setAttribute("rel", "canonical");
    document.head.appendChild(element);
  }

  element.setAttribute("href", href);
}

function setRobots(content: string) {
  setMeta('meta[name="robots"]', "name", "robots", content);
}

/**
 * Applies title, description, canonical, robots, Open Graph and Twitter tags,
 * then swaps the JSON-LD blocks for this route.
 */
export function usePageMeta({
  path,
  structuredData = [],
  index,
  title,
  description,
}: PageMeta): void {
  useEffect(() => {
    const shared = publicRouteMeta(path);
    const resolvedTitle = title ?? shared?.title ?? SITE_NAME;
    const resolvedDescription = description ?? shared?.description ?? "";
    const shouldIndex = index ?? shared?.index ?? false;

    const url = absoluteUrl(path);
    const fullTitle = path === "/" ? resolvedTitle : `${resolvedTitle} | ${SITE_NAME}`;
    const ogImage = absoluteUrl(OG_IMAGE_PATH);

    document.title = fullTitle;

    setMeta('meta[name="description"]', "name", "description", resolvedDescription);
    setCanonical(url);
    setRobots(shouldIndex ? "index, follow" : "noindex, nofollow");

    setMeta("meta[property='og:type']", "property", "og:type", "website");
    setMeta("meta[property='og:site_name']", "property", "og:site_name", SITE_NAME);
    setMeta("meta[property='og:title']", "property", "og:title", fullTitle);
    setMeta("meta[property='og:description']", "property", "og:description", resolvedDescription);
    setMeta("meta[property='og:url']", "property", "og:url", url);
    setMeta("meta[property='og:image']", "property", "og:image", ogImage);
    setMeta("meta[property='og:image:width']", "property", "og:image:width", "1200");
    setMeta("meta[property='og:image:height']", "property", "og:image:height", "630");
    setMeta("meta[property='og:image:alt']", "property", "og:image:alt", OG_IMAGE_ALT);

    setMeta("meta[name='twitter:card']", "name", "twitter:card", "summary_large_image");
    setMeta("meta[name='twitter:title']", "name", "twitter:title", fullTitle);
    setMeta("meta[name='twitter:description']", "name", "twitter:description", resolvedDescription);
    setMeta("meta[name='twitter:image']", "name", "twitter:image", ogImage);
    setMeta("meta[name='twitter:image:alt']", "name", "twitter:image:alt", OG_IMAGE_ALT);

    // Replace any previous route's JSON-LD so structured data always matches the
    // visible content.
    for (const stale of Array.from(
      document.head.querySelectorAll('script[data-seo="jsonld"]'),
    )) {
      stale.remove();
    }

    for (const block of structuredData) {
      const script = document.createElement("script");
      script.type = "application/ld+json";
      script.dataset.seo = "jsonld";
      script.textContent = JSON.stringify(block);
      document.head.appendChild(script);
    }
  }, [title, description, path, index, structuredData]);
}
