import { Upload, UserRound } from "lucide-react";
import type { MouseEvent } from "react";
import { useAuth } from "../auth/AuthContext";
import { CONTACT_PATH, navigateTo, navigateToAnchor } from "../auth/route";

type NavProps = {
  onStartUpload: () => void;
  onOpenAccount: () => void;
  /**
   * Prefix for the in-page section links. Empty on the landing page, "/" on the
   * standalone legal pages so "Pricing" points back at the landing section
   * instead of an anchor that does not exist here.
   */
  sectionBase?: string;
};

/** Leaves a modified click (new tab, new window, download) to the browser. */
function isModifiedClick(event: MouseEvent<HTMLAnchorElement>): boolean {
  return event.defaultPrevented || event.metaKey || event.ctrlKey || event.shiftKey;
}

export function Nav({ onStartUpload, onOpenAccount, sectionBase = "" }: NavProps) {
  const { status, user } = useAuth();
  const isLanding = sectionBase === "";

  // The hrefs stay real, so the links can be copied, opened in a new tab, and
  // indexed; the click is handled in-app so moving between pages does not throw
  // away an unsaved editor session. From a page without those sections, the
  // handler navigates home first and then scrolls.
  const goToSection = (anchor: string) => (event: MouseEvent<HTMLAnchorElement>) => {
    if (isModifiedClick(event) || isLanding) {
      return;
    }

    event.preventDefault();
    navigateToAnchor("/", anchor);
  };

  const goToContact = (event: MouseEvent<HTMLAnchorElement>) => {
    if (isModifiedClick(event)) {
      return;
    }

    event.preventDefault();
    navigateTo(CONTACT_PATH);
  };

  return (
    <header className="nav">
      <div className="nav__inner">
        <a className="brand" href={isLanding ? "#top" : "/"}>
          <span className="brand__mark" aria-hidden="true" />
          <span className="brand__word">Captionline</span>
        </a>

        <nav className="nav__links" aria-label="Primary">
          <a href={`${sectionBase}#how-it-works`} onClick={goToSection("how-it-works")}>
            How it works
          </a>
          <a href={`${sectionBase}#pricing`} onClick={goToSection("pricing")}>
            Pricing
          </a>
          <a href={CONTACT_PATH} onClick={goToContact}>
            Support
          </a>
        </nav>

        <div className="nav__actions">
          <button
            className="button button--ghost button--sm"
            type="button"
            onClick={onOpenAccount}
            aria-label={user ? `Account: ${user.email}` : "Sign in or create an account"}
          >
            <UserRound size={16} aria-hidden="true" />
            <span className="nav__account-label">
              {status === "authenticated" && user ? user.email : "Account"}
            </span>
          </button>

          <button
            className="button button--primary button--sm"
            type="button"
            onClick={onStartUpload}
          >
            <Upload size={16} aria-hidden="true" />
            Upload video
          </button>
        </div>
      </div>
    </header>
  );
}
