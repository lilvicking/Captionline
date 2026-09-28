/**
 * Post-build prerender for Captionline's public SEO routes.
 *
 * The app is a React SPA, so a crawler that does not run JavaScript would
 * otherwise see the same generic tags on every URL. This script writes a real
 * HTML file per public route into the build output, with that route's own
 * title, description, canonical, robots, Open Graph and Twitter tags already in
 * the markup, plus the JSON-LD structured data a crawler reads to understand
 * what the product is and what it costs.
 *
 * It is deliberately small. There are six pages, the metadata already exists in
 * one JSON file, and nothing here needs a browser, a DOM, or a framework:
 *
 *   node scripts/prerender.mjs
 *
 * React still hydrates and takes over exactly as before, because the static
 * markup lives inside the same #root container the app already mounts into.
 *
 * Private routes are never emitted. /admin, /reset-password and /forgot-password
 * are absent from the shared data, so they are absent from the output and
 * robots.txt continues to disallow them.
 */

import { readFile, writeFile, mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..");
const DIST = path.join(ROOT, "dist");

const SITE_URL = "https://captionline.pro";
const SITE_NAME = "Captionline";

const OG_IMAGE_ALT =
  "Captionline — automatic video captions, then edit, style and export.";

/** Minimal escaping for text placed inside a double-quoted attribute. */
function attr(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** Escaping for text that becomes element content. */
function text(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

/**
 * A JSON-LD block.
 *
 * Any `<` inside a string is replaced with its JSON escape before the block is
 * written, so a `</script>` sequence cannot close the tag early. The escape is
 * legal JSON, so the parsed value is unchanged.
 */
function jsonLd(block) {
  return `    <script type="application/ld+json" data-seo="jsonld">${JSON.stringify(block).replace(
    /</g,
    "\\u003c",
  )}</script>`;
}

/**
 * The same documents the React app builds at runtime, assembled from
 * `src/seo/content.json` so a price, an allowance or an FAQ answer has exactly
 * one source of truth.
 *
 * Only the two routes that describe the product emit anything, matching the app
 * exactly. A prerendered block the runtime would immediately strip would leave
 * the two views of the page disagreeing.
 *
 * These carry the `data-seo="jsonld"` attribute the client uses to clear stale
 * blocks, so a browser that does run the script replaces these rather than
 * adding a second copy alongside them.
 */
function structuredDataFor(routePath, facts) {
  if (routePath !== "/" && routePath !== "/caption-generator") {
    return [];
  }

  const softwareApplication = {
    "@context": "https://schema.org",
    "@type": "SoftwareApplication",
    name: SITE_NAME,
    url: routePath === "/" ? `${SITE_URL}/` : `${SITE_URL}${routePath}`,
    applicationCategory: "MultimediaApplication",
    operatingSystem: "Web browser",
    description: facts.mediumDescription,
    featureList: [...facts.capabilities],
    offers: facts.plans.map((plan) => ({
      "@type": "Offer",
      name: `${plan.name} plan`,
      price: String(plan.price),
      priceCurrency: "USD",
      description: `${plan.minutes} processing minutes per ${
        plan.period === "year" ? "year" : "month"
      }.`,
    })),
  };

  const webSite = {
    "@context": "https://schema.org",
    "@type": "WebSite",
    name: SITE_NAME,
    url: SITE_URL,
    description: facts.shortDescription,
  };

  const blocks = [softwareApplication, webSite];

  if (routePath === "/caption-generator") {
    blocks.push({
      "@context": "https://schema.org",
      "@type": "FAQPage",
      mainEntity: facts.faq.map((entry) => ({
        "@type": "Question",
        name: entry.question,
        acceptedAnswer: { "@type": "Answer", text: entry.answer },
      })),
    });
  }

  return blocks;
}

function headTags({ title, description, routePath, ogImage, facts }) {
  const url = routePath === "/" ? `${SITE_URL}/` : `${SITE_URL}${routePath.replace(/\/+$/, "")}`;
  const fullTitle = routePath === "/" ? title : `${title} | ${SITE_NAME}`;
  const image = `${SITE_URL}${ogImage}`;

  return [
    `<title>${text(fullTitle)}</title>`,
    `    <meta name="description" content="${attr(description)}" />`,
    `    <link rel="canonical" href="${attr(url)}" />`,
    `    <meta name="robots" content="index, follow" />`,
    `    <meta property="og:type" content="website" />`,
    `    <meta property="og:site_name" content="${attr(SITE_NAME)}" />`,
    `    <meta property="og:title" content="${attr(fullTitle)}" />`,
    `    <meta property="og:description" content="${attr(description)}" />`,
    `    <meta property="og:url" content="${attr(url)}" />`,
    `    <meta property="og:image" content="${attr(image)}" />`,
    `    <meta property="og:image:width" content="1200" />`,
    `    <meta property="og:image:height" content="630" />`,
    `    <meta property="og:image:alt" content="${attr(OG_IMAGE_ALT)}" />`,
    `    <meta name="twitter:card" content="summary_large_image" />`,
    `    <meta name="twitter:title" content="${attr(fullTitle)}" />`,
    `    <meta name="twitter:description" content="${attr(description)}" />`,
    `    <meta name="twitter:image" content="${attr(image)}" />`,
    `    <meta name="twitter:image:alt" content="${attr(OG_IMAGE_ALT)}" />`,
    structuredDataFor(routePath, facts).map(jsonLd).join("\n    "),
  ].join("\n    ");
}

/**
 * Static body for the search landing page.
 *
 * This is the visible copy a crawler needs. It is informational only: React
 * replaces it on mount, so there is exactly one rendered version for people and
 * no chance of the two drifting in a way a reader could see.
 */
function captionGeneratorBody(facts) {
  const workflow = [
    ["Upload your video", "Choose a file from your device. Captionline measures it and transcribes the audio with word-level timing, so captions can be placed against the words actually spoken."],
    ["Review and edit the captions", "Correct the words and punctuation, adjust the timing, and add anything the automatic pass missed. The export uses the captions you leave here."],
    ["Style the captions", "Set font, size, colour, alignment, spacing, outline, shadow and background, or start from a preset. Position them anywhere, including a precise vertical setting."],
    ["Download the SRT or export the video", "Take a standard SRT subtitle file, or export a finished MP4 with the captions burned in. Neither export uses processing minutes."],
  ];

  const capabilities = [
    ["Automatic video captions", "Upload a video and Captionline produces a timed caption track from its audio, with word-level alignment so each line lands where the speech actually is. Every caption stays editable afterwards."],
    ["Automatic subtitles in SRT", "Captions are generated as a standard subtitle track. Download an SRT file for external subtitle tracks, or keep captions burned in when a viewer has no way to turn them off."],
    ["Caption editing and styling", "Font, size, weight, colour, alignment, letter and word spacing, line height, background, outline, shadow and an exact vertical position, with presets to start from."],
    ["Preview the whole captioned video", "Preview the full length with your captions styled as they will appear, and word-by-word highlighting where word timing is available."],
  ];

  const useCases = [
    "TikTok captions",
    "Instagram Reels captions",
    "YouTube and Shorts captions",
    "Podcast video captions",
    "Accessibility and sound-off viewing",
    "Product and business video",
    "Courses and educators",
    "Creator workflows",
  ];

  const items = (entries) =>
    entries
      .map(
        ([h, p]) =>
          `        <li><h2>${text(h)}</h2><p>${text(p)}</p></li>`,
      )
      .join("\n");

  return `      <div class="seopage">
        <section class="seopage__hero">
          <p class="eyebrow">Caption generator</p>
          <h1 class="seopage__title">Free AI caption generator for video</h1>
          <p class="seopage__lede">Upload a video and Captionline turns the audio into timed
          captions you can read, correct and restyle. Export a standard SRT subtitle file, or
          export a finished video with the captions burned in.</p>
          <div class="seopage__cta">
            <a class="button button--primary" href="/#upload">Start captioning free</a>
            <p class="seopage__cta-note">The free plan includes
            <strong>10 minutes of processing a month</strong>, with editing, styling, full preview,
            SRT download and finished MP4 export all included.</p>
          </div>
        </section>
        <section class="seopage__section">
          <h2 class="seopage__subtitle">How it works</h2>
          <ol class="seopage__steps">
${items(workflow)}
          </ol>
        </section>
        <section class="seopage__section">
          <h2 class="seopage__subtitle">What you can do</h2>
          <ul>
${items(capabilities)}
          </ul>
        </section>
        <section class="seopage__section">
          <h2 class="seopage__subtitle">Made for the places people publish video</h2>
          <ul>
${useCases.map((u) => `            <li>${text(u)}</li>`).join("\n")}
          </ul>
        </section>
        <section class="seopage__section seopage__section--free">
          <h2 class="seopage__subtitle">The free plan is not a trial</h2>
          <p class="seopage__body">The free plan does not expire. It includes 10 minutes of video
          processing every month, and every part of the workflow is available on it: automatic
          transcription, the caption editor, the full caption designer, preview of the whole video,
          SRT download, and export of a finished captioned MP4. Paid plans are for people who need
          more video processed each month: 500 minutes on Creator, 1,500 on Pro.</p>
          <p class="seopage__body"><a href="/pricing">See all plans and monthly allowances</a>.</p>
        </section>
        <section class="seopage__section" id="seopage-faq">
          <h2 class="seopage__subtitle">Questions people ask about automatic captions</h2>
          <dl>
${facts.faq
  .map(
    (entry) =>
      `            <dt>${text(entry.question)}</dt>\n            <dd>${text(entry.answer)}</dd>`,
  )
  .join("\n")}
          </dl>
        </section>
      </div>`;
}

function bodyFor(routePath, facts) {
  if (routePath === "/caption-generator") {
    return captionGeneratorBody(facts);
  }
  return "      <p>Loading…</p>";
}

/**
 * Replaces the starter #root element with this route's static body.
 *
 * The body contains its own nested `</div>` tags, so a non-greedy regex would
 * stop at the first one and silently truncate the content. This walks the
 * element and counts nesting depth to find the real closing tag.
 */
function replaceRoot(html, body) {
  const open = html.indexOf('<div id="root">');

  if (open === -1) {
    throw new Error('prerender: no #root element found in the built index.html');
  }

  const openEnd = open + '<div id="root">'.length;
  let depth = 1;
  let cursor = openEnd;

  while (cursor < html.length && depth > 0) {
    const nextOpen = html.indexOf("<div", cursor);
    const nextClose = html.indexOf("</div>", cursor);

    if (nextClose === -1) {
      throw new Error("prerender: unbalanced #root element");
    }

    if (nextOpen !== -1 && nextOpen < nextClose) {
      depth += 1;
      cursor = nextOpen + 4;
      continue;
    }

    depth -= 1;
    cursor = nextClose + 6;
  }

  // `cursor` sits just past the element's own closing tag, so the closing tag
  // is re-emitted here rather than left off the document.
  return `${html.slice(0, openEnd)}\n${body}\n    </div>${html.slice(cursor)}`;
}

async function main() {
  if (!existsSync(DIST)) {
    console.error("prerender: dist/ not found. Run the build first.");
    process.exit(1);
  }

  const shared = JSON.parse(
    await readFile(path.join(ROOT, "src", "seo", "routes.json"), "utf8"),
  );
  const facts = JSON.parse(
    await readFile(path.join(ROOT, "src", "seo", "content.json"), "utf8"),
  );
  const template = await readFile(path.join(DIST, "index.html"), "utf8");

  const routes = Object.keys(shared.routes);
  const written = [];

  for (const routePath of routes) {
    const meta = shared.routes[routePath];
    const tags = headTags({
      title: meta.title,
      description: meta.description,
      routePath,
      ogImage: shared.ogImage,
      facts,
    });

    // Replace the placeholder title block with this route's head tags, and drop
    // the starter root content in favour of the route's static body.
    let html = template.replace(
      /<title>[\s\S]*?<\/title>/,
      tags,
    );

    // The starter document ships a minimal root; replace it with the route's
    // static body so a crawler sees real content without running JavaScript.
    html = replaceRoot(html, bodyFor(routePath, facts));

    // Starter head tags are replaced wholesale by the block above.
    html = html.replace(
      /<link rel="canonical"[\s\S]*?name="twitter:description"[\s\S]*?\/>/,
      "",
    );

    const outDir = routePath === "/" ? DIST : path.join(DIST, routePath.replace(/^\//, ""));
    await mkdir(outDir, { recursive: true });
    await writeFile(path.join(outDir, "index.html"), html, "utf8");
    written.push(routePath === "/" ? "/" : routePath);
  }

  console.log(`prerender: wrote ${written.length} route(s): ${written.join(", ")}`);

  const leaked = written.filter((p) =>
    ["/admin", "/reset-password", "/forgot-password"].includes(p),
  );
  if (leaked.length > 0) {
    console.error(`prerender: private routes were emitted: ${leaked.join(", ")}`);
    process.exit(1);
  }
}

main().catch((error) => {
  console.error("prerender failed:", error);
  process.exit(1);
});
