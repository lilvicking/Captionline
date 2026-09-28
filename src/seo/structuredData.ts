/**
 * Structured data and the marketing profile used by it.
 *
 * Every field here is a fact Captionline can substantiate. There are no ratings,
 * review counts, user numbers, awards, founding details, or testimonials, because
 * inventing any of them would be a fabricated claim published to every crawler
 * that reads the page.
 */

import { SITE_NAME, SITE_URL, absoluteUrl } from "./site";
import content from "./content.json";

/**
 * The facts below live in `content.json` rather than in this file, because the
 * same claims are also published to `llms.txt` and to the prerendered HTML. One
 * copy of a price, an allowance, or a FAQ answer is the only way to be sure the
 * page, the JSON-LD and the crawler-facing text cannot contradict each other.
 */
const facts = content as {
  tagline: string;
  shortDescription: string;
  mediumDescription: string;
  longDescription: string;
  freePlanSummary: string;
  capabilities: string[];
  categories: string[];
  tags: string[];
  plans: { id: string; name: string; price: number; period: string; minutes: number }[];
  faq: { question: string; answer: string }[];
};

/** The plans, as they actually are. Used for both visible copy and offers. */
export const PLANS = facts.plans;

/** The free plan's headline terms, as stated on the pricing page. */
export const FREE_PLAN_SUMMARY = facts.freePlanSummary;

/** Capabilities stated once, so the page and the structured data agree. */
export const CAPABILITIES = facts.capabilities;

export const SHORT_DESCRIPTION = facts.shortDescription;

export const MEDIUM_DESCRIPTION = facts.mediumDescription;

export const LONG_DESCRIPTION = facts.longDescription;

/** Short, directory-friendly tagline. */
export const TAGLINE = facts.tagline;

export const CATEGORIES = facts.categories;

export const TAGS = facts.tags;

/**
 * The FAQ, written once and used twice: the visible list renders these strings,
 * and the FAQPage structured data is built from the same array, so the
 * machine-readable answers always match what a reader can actually see.
 */
export const FAQ = facts.faq;

/**
 * The application, described only in terms of what it does.
 *
 * `offers` lists the real plan prices. `aggregateRating` and `review` are
 * deliberately absent.
 */
export function softwareApplicationSchema(path = "/") {
  return {
    "@context": "https://schema.org",
    "@type": "SoftwareApplication",
    name: SITE_NAME,
    url: absoluteUrl(path),
    applicationCategory: "MultimediaApplication",
    operatingSystem: "Web browser",
    description: MEDIUM_DESCRIPTION,
    featureList: [...CAPABILITIES],
    offers: PLANS.map((plan) => ({
      "@type": "Offer",
      name: `${plan.name} plan`,
      price: String(plan.price),
      priceCurrency: "USD",
      description: `${plan.minutes} processing minutes per ${plan.period === "year" ? "year" : "month"}.`,
    })),
  };
}

export function webSiteSchema() {
  return {
    "@context": "https://schema.org",
    "@type": "WebSite",
    name: SITE_NAME,
    url: SITE_URL,
    description: SHORT_DESCRIPTION,
  };
}

/**
 * FAQ structured data, built from the same array the page renders, so the
 * machine-readable answers cannot drift from the visible ones.
 */
export function faqPageSchema(entries: { question: string; answer: string }[]) {
  return {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: entries.map((entry) => ({
      "@type": "Question",
      name: entry.question,
      acceptedAnswer: {
        "@type": "Answer",
        text: entry.answer,
      },
    })),
  };
}
