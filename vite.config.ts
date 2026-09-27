import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // Captionline is served from the domain root, so asset URLs are absolute
  // (/assets/...). A relative base ("./") resolves against the current path,
  // which only works for single-segment routes and would break as soon as a
  // nested route such as /legal/terms is added.
  base: "/",
  server: {
    port: 5173,
    watch: {
      // The Python backend lives in this repo. Its virtualenv holds tens of
      // thousands of files, so keep it out of the watcher to avoid spurious
      // full-page reloads while the backend is running.
      ignored: ["**/backend/.venv/**", "**/backend/venv/**", "**/__pycache__/**"],
    },
  },
  build: {
    outDir: "dist",
    // Production must not ship the full unminified client source. Source maps
    // stay off; turn them on locally only with `sourcemap: "inline"` or by
    // running the dev server, which always maps.
    sourcemap: false,
  },
});
