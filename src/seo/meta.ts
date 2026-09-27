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

export type PageMeta = {
  title: string;
  description: string;
  path: string;
  /** JSON-LD documents to attach to the page. */
  structuredData?: Record<string, unknown>[];
  /** Defaults to indexing. Set false for private or single-use routes. */
  index?: boolean;
};

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
  title,
  description,
  path,
  structuredData = [],
  index = true,
}: PageMeta): void {
  useEffect(() => {
    const url = absoluteUrl(path);
    const fullTitle = path === "/" ? title : `${title} | ${SITE_NAME}`;

    document.title = fullTitle;

    setMeta('meta[name="description"]', "name", "description", description);
    setCanonical(url);
    setRobots(index ? "index, follow" : "noindex, nofollow");

    setMeta("meta[property='og:type']", "property", "og:type", "website");
    setMeta("meta[property='og:site_name']", "property", "og:site_name", SITE_NAME);
    setMeta("meta[property='og:title']", "property", "og:title", fullTitle);
    setMeta("meta[property='og:description']", "property", "og:description", description);
    setMeta("meta[property='og:url']", "property", "og:url", url);

    setMeta("meta[name='twitter:card']", "name", "twitter:card", "summary_large_image");
    setMeta("meta[name='twitter:title']", "name", "twitter:title", fullTitle);
    setMeta("meta[name='twitter:description']", "name", "twitter:description", description);

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
