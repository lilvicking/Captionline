import { Upload } from "lucide-react";

type NavProps = {
  onStartUpload: () => void;
};

export function Nav({ onStartUpload }: NavProps) {
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

        <button className="button button--primary button--sm" type="button" onClick={onStartUpload}>
          <Upload size={16} aria-hidden="true" />
          Upload video
        </button>
      </div>
    </header>
  );
}
