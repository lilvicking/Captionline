import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "./",
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
    sourcemap: true,
  },
});
