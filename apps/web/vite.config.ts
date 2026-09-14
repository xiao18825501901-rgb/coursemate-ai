import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type { Plugin, ViteDevServer } from "vite";
import { defineConfig } from "vitest/config";

/**
 * Apply the production document routing while developing.
 *
 * The decision table mirrors `netlify.toml` and `scripts/serve_web_dist.mjs`:
 *
 *   "/" and unknown paths → ui.html   (refreshed shell is the DEFAULT entry)
 *   "/app", "/app/*"      → ui.html   (compatibility alias)
 *   legacy deep links    → index.html (previous site stays reachable)
 *
 * Vite would otherwise serve `index.html` for every unmatched path, so without
 * this middleware the development and deployed URL shapes would diverge.
 */

const LEGACY_PREFIXES = ["qa", "learn", "courses", "tasks", "documents", "admin", "about"];

function firstSegment(pathname: string): string {
  return pathname.split("/").filter(Boolean)[0] ?? "";
}

function documentFor(pathname: string): "ui.html" | "index.html" {
  if (pathname === "/" || pathname === "") return "ui.html";
  if (pathname === "/app" || pathname.startsWith("/app/")) return "ui.html";
  if (LEGACY_PREFIXES.includes(firstSegment(pathname))) return "index.html";
  return "ui.html";
}

function routeDocuments(): Plugin {
  const uiDocument = fileURLToPath(new URL("./ui.html", import.meta.url));
  const legacyDocument = fileURLToPath(new URL("./index.html", import.meta.url));
  return {
    name: "coursemate-route-documents",
    apply: "serve",
    configureServer(server: ViteDevServer) {
      server.middlewares.use((request, response, next) => {
        const url = decodeURIComponent((request.url ?? "").split("?")[0] ?? "");
        const looksLikeFile =
          /\/@/.test(url) || // Vite internals: /@vite/client, /@react-refresh, /@id/…
          /\/src\//.test(url) || // application sources
          /\/node_modules\//.test(url) || // pre-bundled dependency modules
          /\.[a-z0-9]+$/i.test(url); // any real file (fonts, svg, js served directly)
        // Real resources are left to Vite's own resolution, exactly as deployed
        // assets win over Netlify rewrites.
        if (url === "/ui.html" || url === "/index.html" || looksLikeFile) {
          next();
          return;
        }
        const document = documentFor(url);
        server
          .transformIndexHtml(
            `/${document}`,
            readFileSync(document === "ui.html" ? uiDocument : legacyDocument, "utf-8"),
          )
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
  plugins: [react(), routeDocuments()],
  server: {
    port: 5173,
  },
  build: {
    rollupOptions: {
      // Two documents from one project. The refreshed shell (ui.html) is the
      // default document; the previous site (index.html) keeps its deep links.
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
