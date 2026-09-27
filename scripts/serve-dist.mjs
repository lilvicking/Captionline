#!/usr/bin/env node
/**
 * Production static server for the Captionline web app.
 *
 * Captionline is a single-page app with real routes (/terms, /privacy, /contact,
 * /reset-password). A plain static file server answers those paths with 404,
 * because no such file exists on disk, and the emailed password-reset links
 * stop working. This server resolves a request in three steps:
 *
 *   1. A real file under dist/ is served as-is.
 *   2. A missing *asset* request (anything under /assets/, or a path whose last
 *      segment looks like a filename) is a 404. Returning index.html there
 *      would hand a broken <script> to the browser and surface as a confusing
 *      MIME-type error instead of an honest 404.
 *   3. Everything else is a client-side route, so it serves index.html and lets
 *      the app router take over. This is the SPA history fallback.
 *
 * Only Node built-ins are used, deliberately. The web app has three runtime
 * dependencies and adding a server framework for a directory of four files
 * would be the wrong trade. It also means this works no matter which
 * dependencies the platform keeps after the build, since Node itself is always
 * present.
 *
 * Configuration comes from the environment: PORT is required, and the server
 * binds 0.0.0.0 so a platform proxy can reach it.
 */

import { createReadStream, statSync } from "node:fs";
import { createServer } from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));

/** The built app. Resolved from this file so the working directory is irrelevant. */
const ROOT = path.resolve(HERE, "..", "dist");
const INDEX = path.join(ROOT, "index.html");

/** Bind on every interface: a platform proxy connects from outside the container. */
const HOST = "0.0.0.0";

/** Content types for the file kinds a Vite build emits. */
const CONTENT_TYPES = new Map(
  Object.entries({
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".map": "application/json; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".xml": "application/xml; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".gif": "image/gif",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
  }),
);

const DEFAULT_CONTENT_TYPE = "application/octet-stream";

function startupFailure(message) {
  process.stderr.write(`\nserve-dist: ${message}\n\n`);
  process.exit(1);
}

/**
 * Resolve the port, refusing to guess.
 *
 * A missing or malformed PORT would otherwise bind 8080 or 0 and fail Railway's
 * health check with a message that says nothing about the cause.
 */
function readPort() {
  const raw = process.env.PORT;

  if (raw === undefined || raw.trim() === "") {
    startupFailure(
      "PORT is not set. Set it to the port this server should listen on, for example:\n" +
        "  PORT=8080 npm start",
    );
  }

  const port = Number(raw.trim());

  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    startupFailure(
      `PORT must be an integer between 1 and 65535, but was ${JSON.stringify(raw)}.`,
    );
  }

  return port;
}

function statOrNull(target) {
  try {
    const stats = statSync(target);
    return stats.isFile() ? stats : null;
  } catch {
    return null;
  }
}

function isDirectory(target) {
  try {
    return statSync(target).isDirectory();
  } catch {
    return false;
  }
}

function contentTypeFor(filePath) {
  return CONTENT_TYPES.get(path.extname(filePath).toLowerCase()) ?? DEFAULT_CONTENT_TYPE;
}

/**
 * A request for a specific file rather than a client-side route.
 *
 * Without this, a typo in a script name would return index.html and the browser
 * would report a MIME mismatch several layers away from the real problem.
 */
function isAssetRequest(pathname) {
  if (pathname.startsWith("/assets/")) {
    return true;
  }
  return pathname.slice(pathname.lastIndexOf("/") + 1).includes(".");
}

/**
 * Map a URL path to a file inside ROOT, or report why it cannot.
 *
 * Defence in depth on traversal: the WHATWG URL parser already collapses `..`
 * segments, but percent-encoded ones (`%2e%2e`, `%2f`) survive parsing and only
 * become dangerous after decoding. Backslashes are folded to forward slashes
 * first, because they are separators on Windows and would otherwise sneak past
 * a POSIX-only normalisation.
 */
function resolveRequestPath(pathname) {
  let decoded;
  try {
    decoded = decodeURIComponent(pathname);
  } catch {
    return { error: 400 };
  }

  if (decoded.includes("\0")) {
    return { error: 400 };
  }

  const normalized = path.posix.normalize(decoded.replace(/\\/g, "/"));
  const candidate = path.resolve(ROOT, `.${normalized}`);

  // `path.relative` is separator-aware, so this holds on Windows and POSIX.
  const relative = path.relative(ROOT, candidate);
  if (relative.startsWith("..") || path.isAbsolute(relative)) {
    return { error: 403 };
  }

  return { filePath: candidate };
}

/** Send a short body without leaking internal paths. */
function sendText(response, statusCode, text) {
  const body = Buffer.from(text, "utf-8");
  response.writeHead(statusCode, {
    "Content-Type": "text/plain; charset=utf-8",
    "Content-Length": body.length,
    "X-Content-Type-Options": "nosniff",
  });
  response.end(body);
}

function serveFile(request, response, filePath, stats, isDocument) {
  response.writeHead(200, {
    "Content-Type": contentTypeFor(filePath),
    "Content-Length": stats.size,
    "Last-Modified": stats.mtime.toUTCString(),
    "X-Content-Type-Options": "nosniff",
    // Build output is content-hashed, so it is safe to cache for a year. The
    // document is not hashed and must revalidate or a deploy would keep serving
    // the previous asset names.
    "Cache-Control": isDocument
      ? "no-cache"
      : "public, max-age=31536000, immutable",
  });

  // HEAD advertises the same headers with no body.
  if (request.method === "HEAD") {
    response.end();
    return;
  }

  const stream = createReadStream(filePath);

  stream.on("error", () => {
    // The file disappeared between the stat and the read, or the disk failed.
    response.destroy();
  });

  stream.pipe(response);
}

function handle(request, response) {
  if (request.method !== "GET" && request.method !== "HEAD") {
    response.writeHead(405, {
      Allow: "GET, HEAD",
      "Content-Type": "text/plain; charset=utf-8",
    });
    response.end("Method Not Allowed\n");
    return;
  }

  let pathname;
  try {
    // The query string is not part of the filesystem path, so
    // /reset-password?token=abc resolves to /reset-password.
    pathname = new URL(request.url, "http://localhost").pathname;
  } catch {
    sendText(response, 400, "Bad Request\n");
    return;
  }

  const resolved = resolveRequestPath(pathname);

  if (resolved.error) {
    sendText(response, resolved.error, "Bad Request\n");
    return;
  }

  let target = resolved.filePath;
  let stats = statOrNull(target);

  if (!stats && isDirectory(target)) {
    if (target === ROOT) {
      // The site root is the app document.
      target = INDEX;
      stats = statOrNull(INDEX);
    } else {
      // Any other directory is not browsable, and must not leak an index file.
      sendText(response, 404, "Not Found\n");
      return;
    }
  }

  // Whether we end up serving the app document rather than a build artifact.
  // Mutable because the SPA-fallback branch below reassigns it.
  let isDocument = target === INDEX;

  if (!stats) {
    if (isAssetRequest(pathname)) {
      sendText(response, 404, "Not Found\n");
      return;
    }
    // A client-side route: hand over the document and let the app route it.
    target = INDEX;
    stats = statOrNull(INDEX);
    isDocument = true;

    if (!stats) {
      // The build is incomplete. Report it without killing the process, and
      // without telling the client where anything lives on disk.
      sendText(response, 500, "Internal Server Error\n");
      return;
    }
  }

  serveFile(request, response, target, stats, isDocument);
}

const port = readPort();

if (!statOrNull(INDEX)) {
  startupFailure(
    `no build found in ${path.relative(process.cwd(), ROOT) || ROOT}. ` +
      'Run "npm run build" before starting.',
  );
}

const server = createServer((request, response) => {
  try {
    handle(request, response);
  } catch {
    // Never surface a stack trace or a filesystem path to the client.
    if (!response.headersSent) {
      sendText(response, 500, "Internal Server Error\n");
    } else {
      response.destroy();
    }
  }
});

// A platform sends SIGTERM on redeploy; close cleanly so the port is released.
for (const signal of ["SIGTERM", "SIGINT"]) {
  process.on(signal, () => server.close(() => process.exit(0)));
}

server.listen(port, HOST, () => {
  process.stdout.write(
    `serve-dist: listening on http://${HOST}:${port}, serving ${path.relative(
      process.cwd(),
      ROOT,
    ) || ROOT}\n`,
  );
});
