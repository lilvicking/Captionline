/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * Base URL of the Captionline transcription service.
   *
   * Local development defaults to http://localhost:8000. In production set this
   * to the deployed backend origin (for example the Railway service URL) so no
   * source change is required.
   */
  readonly VITE_API_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
