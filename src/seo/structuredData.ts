/**
 * Structured data and the marketing profile used by it.
 *
 * Every field here is a fact Captionline can substantiate. There are no ratings,
 * review counts, user numbers, awards, founding details, or testimonials, because
 * inventing any of them would be a fabricated claim published to every crawler
 * that reads the page.
 */

import { SITE_NAME, SITE_URL, absoluteUrl } from "./site";

/** The plans, as they actually are. Used for both visible copy and offers. */
export const PLANS = [
  {
    id: "free",
    name: "Free",
    price: 0,
    period: "month",
    minutes: 10,
  },
  {
    id: "creator",
    name: "Creator",
    price: 19,
    period: "month",
    minutes: 500,
  },
  {
    id: "pro",
    name: "Pro",
    price: 39,
    period: "month",
    minutes: 1500,
  },
  {
    id: "creator-annual",
    name: "Creator Annual",
    price: 149,
    period: "year",
    minutes: 500,
  },
] as const;

export const FREE_PLAN_SUMMARY =
  "10 processing minutes a month, with caption editing, the full Caption Designer, full preview, SRT download and finished MP4 export included.";

/** Capabilities stated once, so the page and the structured data agree. */
export const CAPABILITIES = [
  "Automatic transcription of uploaded video and audio with word-level timing",
  "An editor for the generated caption track, including the words and punctuation",
  "A caption designer for font, size, weight, colour, alignment, spacing, outline, shadow and background",
  "Full-length preview of the captioned video",
  "Subtitle download as an SRT file",
  "Export of a finished captioned video with the captions burned in",
] as const;

export const SHORT_DESCRIPTION =
  "Automatic video captions and subtitles you can edit, style and export as SRT or a finished captioned MP4.";

export const MEDIUM_DESCRIPTION =
  "Captionline is an online caption and subtitle workflow: upload a video, generate timed captions automatically, edit and style them, preview the result, then download an SRT file or export a finished captioned video.";

export const LONG_DESCRIPTION =
  "Captionline turns an uploaded video into an editable, stylable caption track. Upload a video, and Captionline transcribes the audio with word-level timing; edit the words and punctuation in the caption editor; choose a look in the caption designer, from font and size to colour, alignment, spacing, outline, shadow and background; preview the full captioned video; then download a standard SRT subtitle file or export a finished MP4 with the captions burned in. Every plan includes the whole workflow. The difference between plans is how much video can be processed each month: the free plan includes 10 processing minutes a month, and paid plans raise that to 500 or 1,500 minutes.";

/** Short, directory-friendly tagline. */
export const TAGLINE = "Automatic video captions, styled and exported";

export const CATEGORIES = [
  "Video editing",
  "Subtitles & captions",
  "Transcription",
  "Content creation",
  "Social media video",
  "Accessibility",
];

export const TAGS = [
  "AI caption generator",
  "automatic subtitles",
  "video to text",
  "SRT generator",
  "burn in captions",
  "closed captions",
  "video transcription",
  "caption editor",
  "subtitle editor",
  "caption styling",
];

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
