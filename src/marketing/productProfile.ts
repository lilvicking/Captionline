/**
 * Canonical public marketing profile.
 *
 * A single source for the copy used in directory and launch submissions —
 * Product Hunt, SaaSHub, AlternativeTo, Uneed and similar. Everything here is a
 * capability Captionline actually has.
 *
 * This file deliberately contains no secrets, no internal identifiers, no
 * Stripe details, and no customer information. It is public marketing copy and is
 * safe to read, quote and submit.
 */

import {
  CAPABILITIES,
  CATEGORIES,
  FREE_PLAN_SUMMARY,
  LONG_DESCRIPTION,
  MEDIUM_DESCRIPTION,
  PLANS,
  SHORT_DESCRIPTION,
  TAGLINE,
  TAGS,
} from "../seo/structuredData";
import { SITE_NAME, SITE_URL } from "../seo/site";

export const productProfile = {
  name: SITE_NAME,
  url: SITE_URL,
  tagline: TAGLINE,
  shortDescription: SHORT_DESCRIPTION,
  mediumDescription: MEDIUM_DESCRIPTION,
  longDescription: LONG_DESCRIPTION,
  categories: [...CATEGORIES],
  tags: [...TAGS],
  capabilities: [...CAPABILITIES],
  freePlan: FREE_PLAN_SUMMARY,
  pricing: PLANS.map((plan) => ({
    name: plan.name,
    price: plan.price,
    currency: "USD",
    interval: plan.period,
    processingMinutes: plan.minutes,
  })),
  primaryLandingPage: `${SITE_URL}/caption-generator`,
  categoriesForListings: [
    "Video & Audio",
    "Productivity",
    "Content & Social Media",
    "AI",
  ],
} as const;

/**
 * Deliberately absent, and why.
 *
 * The Product Hunt badge belongs in the footer once there is a real launch URL.
 * Until then a badge would either be broken or, worse, point somewhere that is
 * not Captionline. When the launch happens, add the link to `Footer.tsx` beside
 * the other footer links, and only then.
 */
export const PRODUCT_HUNT_LAUNCH_URL: string | null = null;
