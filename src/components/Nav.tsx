import { Upload, UserRound } from "lucide-react";
import { useAuth } from "../auth/AuthContext";

type NavProps = {
  onStartUpload: () => void;
  onOpenAccount: () => void;
};

export function Nav({ onStartUpload, onOpenAccount }: NavProps) {
  const { status, user } = useAuth();

  return (
    <header className="nav">
      <div className="nav__inner">
        <a className="brand" href="#top">
          <span className="brand__mark" aria-hidden="true" />
          <span className="brand__word">Captionline</span>
        </a>

        <nav className="nav__links" aria-label="Primary">
          <a href="#how-it-works">How it works</a>
          <a href="#pricing">Pricing</a>
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
