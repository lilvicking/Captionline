/**
 * Manual IndexNow submission.
 *
 * IndexNow tells Bing, Yandex and participating search engines that a specific
 * URL has changed, so a re-crawl can happen without waiting for the normal
 * crawl interval. It is a notification, not a ranking signal.
 *
 * This runs only when it is asked for:
 *
 *   npm run indexnow                       # every public URL
 *   npm run indexnow -- /pricing /terms    # only these paths
 *
 * It is deliberately not part of `npm run build`. A build should not reach the
 * network, a failed submission should never fail a deploy, and a build on a
 * contributor's machine has no business telling a search engine that something
 * changed.
 *
 * The key below must match the filename and contents of the file served at
 * https://captionline.pro/<key>.txt, which is how IndexNow proves the caller
 * owns the host. The key is public by design and is not a secret.
 */

import { readFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..");

const SITE_URL = "https://captionline.pro";
const ENDPOINT = "https://api.indexnow.org/indexnow";

/** Must match public/<key>.txt. */
const KEY = "6df193ae031db9a06abde731dd747d7f";

/** The six public pages, read from the same file the sitemap is built from. */
async function publicPaths() {
  const shared = JSON.parse(
    await readFile(path.join(ROOT, "src", "seo", "routes.json"), "utf8"),
  );

  return Object.keys(shared.routes);
}

function absolute(path) {
  if (path === "/") {
    return `${SITE_URL}/`;
  }
  return `${SITE_URL}${path.replace(/\/+$/, "")}`;
}

async function main() {
  const requested = process.argv.slice(2);
  const paths = requested.length > 0 ? requested : await publicPaths();

  if (!existsSync(path.join(ROOT, "public", `${KEY}.txt`))) {
    console.error(`indexnow: public/${KEY}.txt is missing, so the key cannot be verified.`);
    process.exit(1);
  }

  const payload = {
    host: "captionline.pro",
    key: KEY,
    keyLocation: absolute(`/${KEY}.txt`),
    urlList: paths.map(absolute),
  };

  let response;
  try {
    response = await fetch(ENDPOINT, {
      method: "POST",
      headers: {
        "Content-Type": "application/json; charset=utf-8",
      },
      body: JSON.stringify(payload),
    });
  } catch (error) {
    console.error(`indexnow: could not reach ${ENDPOINT}: ${error.message}`);
    process.exit(1);
  }

  console.log(`indexnow: submitted ${payload.urlList.length} URL(s) to ${ENDPOINT}`);

  // 200 and 202 both mean accepted. Anything else is worth reading.
  if (response.status === 200 || response.status === 202) {
    console.log(`indexnow: accepted (HTTP ${response.status})`);
    return;
  }

  console.error(`indexnow: rejected (HTTP ${response.status})`);
  console.error(await response.text());
  process.exit(1);
}

main().catch((error) => {
  console.error("indexnow failed:", error);
  process.exit(1);
});
