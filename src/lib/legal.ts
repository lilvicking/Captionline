/**
 * Legal document versions.
 *
 * The backend owns the version and effective date of the Terms and the Privacy
 * Policy so a change is a deploy, not a code edit. This client is deliberately
 * forgiving: if the endpoint is missing (404) or unreachable, the pages render
 * without a version line. A missing version must never take a legal page down,
 * because the page itself is what people need when something has gone wrong.
 *
 * The contract, exactly as `LegalVersionsResponse` serialises it:
 *
 *   { terms_version, terms_effective_date, privacy_version, privacy_effective_date,
 *     support_email, support_email_configured, governing_law }
 *
 * That flat shape is the primary one read below. Nested `{terms, privacy}`
 * entries and a list shape are still accepted as fallbacks, so a backend that
 * changes its mind leaves the pages rendering rather than silently blanking the
 * version line. Every reader is total: a document missing either half of its
 * pair (a version with no date, or the reverse) resolves to null, which renders
 * as "no version line" instead of a half-populated string.
 */

import { API_BASE_URL } from "./api";

export type LegalVersion = {
  /** Opaque document identifier, e.g. "terms" or "privacy". */
  version: string;
  /** ISO-8601 date the current text took effect. */
  effectiveAt: string;
  /** Free-text label, when the server supplies one. */
  label?: string;
};

export type LegalVersions = {
  terms: LegalVersion | null;
  privacy: LegalVersion | null;
};

const EMPTY: LegalVersions = { terms: null, privacy: null };

function readString(source: Record<string, unknown>, ...keys: string[]): string | null {
  for (const key of keys) {
    const value = source[key];
    if (typeof value === "string" && value.trim() !== "") {
      return value;
    }
  }
  return null;
}

/**
 * Reads one document entry out of the response.
 *
 * The server may return a map keyed by document or a list of entries; both are
 * accepted so a shape change cannot leave the page blank.
 */
function toEntry(value: unknown): LegalVersion | null {
  if (typeof value !== "object" || value === null) {
    return null;
  }

  const record = value as Record<string, unknown>;
  const version = readString(record, "version", "id", "name");
  const effectiveAt = readString(record, "effective_at", "effectiveAt", "effective_date", "date");

  if (!version || !effectiveAt) {
    return null;
  }

  const label = readString(record, "label", "title");
  return { version, effectiveAt, ...(label ? { label } : {}) };
}

function fromMap(payload: unknown): LegalVersions {
  if (typeof payload !== "object" || payload === null) {
    return EMPTY;
  }

  const record = payload as Record<string, unknown>;
  const container =
    typeof record.documents === "object" && record.documents !== null
      ? (record.documents as Record<string, unknown>)
      : record;

  // Flat first: that is what the backend actually returns today, so it is the
  // shape this reader is written against. The nested entries are a fallback for
  // a future response that groups documents, never the other way round.
  return {
    terms:
      flatEntry(container, "terms") ?? toEntry(container.terms) ?? toEntry(record.terms),
    privacy:
      flatEntry(container, "privacy") ?? toEntry(container.privacy) ?? toEntry(record.privacy),
  };
}

/**
 * Reads `<prefix>_version` plus `<prefix>_effective_date` off the flat shape.
 *
 * Both halves are required. A document that carries a version but no effective
 * date (or the reverse) resolves to null rather than to a half-rendered entry,
 * so a truncated response cannot put a bare "Version 2026-09-27" on a legal page
 * with no date attached to it.
 */
function flatEntry(source: Record<string, unknown>, prefix: "terms" | "privacy"): LegalVersion | null {
  const version = readString(source, `${prefix}_version`);
  const effectiveAt = readString(
    source,
    `${prefix}_effective_date`,
    `${prefix}_effective_at`,
  );

  if (!version || !effectiveAt) {
    return null;
  }

  return { version, effectiveAt };
}

function fromList(payload: unknown): LegalVersions {
  if (!Array.isArray(payload)) {
    return EMPTY;
  }

  const versions: LegalVersions = { terms: null, privacy: null };

  for (const item of payload) {
    if (typeof item !== "object" || item === null) {
      continue;
    }

    const record = item as Record<string, unknown>;
    const entry = toEntry(record);
    const document = readString(record, "document", "document_id", "key");

    if (!entry) {
      continue;
    }

    if (document === "terms" || (!document && versions.terms === null)) {
      versions.terms = entry;
    } else if (document === "privacy") {
      versions.privacy = entry;
    }
  }

  return versions;
}

/**
 * Resolves to nulls when the endpoint is absent, so nothing renders a version.
 *
 * `support_email` and `governing_law` in the same response are deliberately
 * ignored: the frontend is configured through VITE_SUPPORT_EMAIL and
 * VITE_GOVERNING_LAW, and a server-side placeholder string must never be
 * printed as if it were a real jurisdiction or a real mailbox.
 */
export async function fetchLegalVersions(): Promise<LegalVersions> {
  try {
    const response = await fetch(`${API_BASE_URL}/api/legal/versions`);

    if (!response.ok) {
      // 404 means this backend does not publish versions yet, which is fine.
      return EMPTY;
    }

    const payload: unknown = await response.json();
    return Array.isArray(payload) ? fromList(payload) : fromMap(payload);
  } catch {
    return EMPTY;
  }
}

/** "Effective 3 March 2026 · version 2026-03-01", or null when unknown. */
export function formatLegalVersion(entry: LegalVersion | null): string | null {
  if (!entry) {
    return null;
  }

  const parsed = new Date(entry.effectiveAt);
  const date = Number.isNaN(parsed.getTime())
    ? entry.effectiveAt
    : parsed.toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" });

  return `Version ${entry.version} · effective ${date}`;
}
