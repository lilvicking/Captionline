export function Footer() {
  return (
    <footer className="footer">
      <div className="footer__inner">
        <span className="brand brand--footer">
          <span className="brand__mark" aria-hidden="true" />
          <span className="brand__word">Captionline</span>
        </span>

        <p className="footer__note">
          Videos are transcribed by WhisperX and deleted after processing. Free previews are limited
          to 30 seconds.
        </p>
      </div>
    </footer>
  );
}
