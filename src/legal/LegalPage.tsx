/**
 * Shared layout for the standalone legal pages.
 *
 * The pages are long-form reading, not an app screen: one column, generous line
 * height, a contents list so a reader can jump to a clause, and a pager to the
 * other legal documents. All copy is passed in as data and rendered as text, so
 * nothing here can turn document content into markup.
 */

import { useEffect, useState } from "react";
import type { MouseEvent, ReactNode } from "react";
import { CONTACT_PATH, navigateTo, navigateToAnchor, PRIVACY_PATH, TERMS_PATH } from "../auth/route";
import { fetchLegalVersions, formatLegalVersion } from "../lib/legal";
import type { LegalVersion } from "../lib/legal";

/**
 * A link to another Captionline page.
 *
 * The href is real, so the address can be copied and crawled, and a plain left
 * click is handled in-app. That keeps the legal pages navigable on a host whose
 * static rewrite is not configured yet, instead of 404-ing on a full page load.
 * A `#section` in the href is scrolled to after the destination renders.
 */
export function LegalLink({ href, children }: { href: string; children: ReactNode }) {
  const follow = (event: MouseEvent<HTMLAnchorElement>) => {
    if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.shiftKey) {
      return;
    }

    event.preventDefault();

    const hashIndex = href.indexOf("#");

    if (hashIndex >= 0) {
      navigateToAnchor(href.slice(0, hashIndex) || "/", href.slice(hashIndex + 1));
      return;
    }

    navigateTo(href);
  };

  return (
    <a href={href} onClick={follow}>
      {children}
    </a>
  );
}

export type LegalSection = {
  /** Anchor id, also used for the contents link. */
  id: string;
  heading: string;
  body: ReactNode;
};

type DocumentKey = "terms" | "privacy";

type LegalPageProps = {
  /**
   * Which versioned document this is. Left off for pages that are not a
   * versioned document, such as Support, so no version line is invented.
   */
  document?: DocumentKey;
  title: string;
  lede: string;
  sections: LegalSection[];
  /** Rendered under the lede, e.g. a visible gap in an unconfigured clause. */
  note?: ReactNode;
};

const PAGER: { href: string; label: string }[] = [
  { href: TERMS_PATH, label: "Terms of Service" },
  { href: PRIVACY_PATH, label: "Privacy Policy" },
  { href: CONTACT_PATH, label: "Support" },
];

/**
 * Reads the published version for one document.
 *
 * Starts null so the page renders immediately; a missing endpoint (404) simply
 * leaves the version line off.
 */
function useLegalVersion(document: DocumentKey | undefined): LegalVersion | null {
  const [entry, setEntry] = useState<LegalVersion | null>(null);

  useEffect(() => {
    if (document === undefined) {
      return;
    }

    let canceled = false;

    void fetchLegalVersions().then((versions) => {
      if (!canceled) {
        setEntry(versions[document]);
      }
    });

    return () => {
      canceled = true;
    };
  }, [document]);

  return entry;
}

export function LegalPage({ document, title, lede, sections, note }: LegalPageProps) {
  const version = useLegalVersion(document);
  const versionLine = formatLegalVersion(version);

  return (
    <section className="legal">
      <div className="legal__inner">
        <header className="legal__head">
          <p className="eyebrow">Legal</p>
          <h1 className="legal__title">{title}</h1>
          <p className="legal__lede">{lede}</p>

          {versionLine ? <p className="legal__version">{versionLine}</p> : null}
          {note}
        </header>

        <nav className="legal__toc" aria-label={`${title} contents`}>
          <p className="legal__toc-title">Contents</p>
          <ol className="legal__toc-list">
            {sections.map((section) => (
              <li key={section.id}>
                <a href={`#${section.id}`}>{section.heading}</a>
              </li>
            ))}
          </ol>
        </nav>

        <div className="legal__body">
          {sections.map((section) => (
            <section
              className="legal__section"
              id={section.id}
              key={section.id}
              aria-labelledby={`${section.id}-heading`}
            >
              <h2 className="legal__heading" id={`${section.id}-heading`}>
                {section.heading}
              </h2>
              <div className="legal__prose">{section.body}</div>
            </section>
          ))}
        </div>

        <nav className="legal__pager" aria-label="Other legal pages">
          {PAGER.filter((entry) => entry.href !== `/${document ?? ""}`).map((entry) => (
            <LegalLink href={entry.href} key={entry.href}>
              <span className="legal__pager-link">{entry.label}</span>
            </LegalLink>
          ))}
        </nav>
      </div>
    </section>
  );
}
