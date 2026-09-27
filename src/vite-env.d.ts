/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * Public site origin used for canonical URLs, the sitemap and structured
   * data. Defaults to the production domain; override for local builds.
   */
  readonly VITE_SITE_URL?: string;

  /**
   * Base URL of the Captionline transcription service.
   *
   * Local development defaults to http://localhost:8000. In production set this
   * to the deployed backend origin (for example the Railway service URL) so no
   * source change is required.
   */
  readonly VITE_API_URL?: string;

  /**
   * Support address published on the /contact page and the legal documents.
   *
   * Optional. When it is unset the pages say email support is not yet available
   * rather than showing an address nobody watches, so no working-looking but
   * unowned mailbox is ever published. Keep it aligned with the backend's
   * SUPPORT_EMAIL.
   */
  readonly VITE_SUPPORT_EMAIL?: string;

  /**
   * The law and forum the Terms of Service are governed by.
   *
   * Optional. When it is unset the Terms state plainly that the clause is not
   * published yet instead of naming an invented jurisdiction. Must be set
   * before the service takes paid subscriptions.
   */
  readonly VITE_GOVERNING_LAW?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
