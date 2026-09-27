import type { MouseEvent } from "react";
import { CONTACT_PATH, navigateTo, PRIVACY_PATH, TERMS_PATH } from "../auth/route";

/** Document links, in the order they are read. */
const LINKS: { href: string; label: string }[] = [
  { href: TERMS_PATH, label: "Terms" },
  { href: PRIVACY_PATH, label: "Privacy" },
  { href: CONTACT_PATH, label: "Contact" },
];

export function Footer() {
  // Real anchors, so the addresses can be copied and crawled. A plain left click
  // is handled in-app to avoid a full reload; modified clicks fall through to the
  // browser as normal.
  const follow = (event: MouseEvent<HTMLAnchorElement>, path: string) => {
    if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.shiftKey) {
      return;
    }

    event.preventDefault();
    navigateTo(path);
  };

  return (
    <footer className="footer">
      <div className="footer__inner">
        <span className="brand brand--footer">
          <span className="brand__mark" aria-hidden="true" />
          <span className="brand__word">Captionline</span>
        </span>

        <p className="footer__note">
          Videos are transcribed by WhisperX and deleted shortly after processing. Every plan
          includes the full finished preview.
        </p>

        <nav className="footer__links" aria-label="Legal">
          {LINKS.map((link) => (
            <a key={link.href} href={link.href} onClick={(event) => follow(event, link.href)}>
              {link.label}
            </a>
          ))}
        </nav>
      </div>
    </footer>
  );
}
