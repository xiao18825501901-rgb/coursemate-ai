import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type { Plugin, ViteDevServer } from "vite";
import { defineConfig } from "vitest/config";

/**
 * Serve the refreshed shell's document at `/app` while developing.
 *
 * Vite serves `ui.html` at `/ui.html` and falls back to `index.html` for any other
 * path, so without this middleware `http://127.0.0.1:5173/app` would return the
 * legacy document. Production performs the same rewrite in `netlify.toml`, so the
 * development and deployed URL shapes stay identical.
 */
function serveUiDocumentAtApp(): Plugin {
  const uiDocument = fileURLToPath(new URL("./ui.html", import.meta.url));
  return {
    name: "coursemate-serve-ui-document-at-app",
    apply: "serve",
    configureServer(server: ViteDevServer) {
      server.middlewares.use((request, response, next) => {
        const url = (request.url ?? "").split("?")[0] ?? "";
        if (url !== "/app" && !url.startsWith("/app/")) {
          next();
          return;
        }
        server
          .transformIndexHtml("/ui.html", readFileSync(uiDocument, "utf-8"))
          .then((html) => {
            response.setHeader("Content-Type", "text/html; charset=utf-8");
            response.end(html);
          })
          .catch(next);
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), serveUiDocumentAtApp()],
  server: {
    port: 5173,
  },
  build: {
    rollupOptions: {
      // Two documents from one project: the existing site keeps `index.html`,
      // and the refreshed CourseMate shell is served from `ui.html` at `/app`.
      input: {
        main: "index.html",
        ui: "ui.html",
      },
    },
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    restoreMocks: true,
    setupFiles: ["./src/test/setup.ts"],
    testTimeout: 15_000,
  },
});
