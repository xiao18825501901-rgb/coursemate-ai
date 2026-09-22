import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type { Plugin, ViteDevServer } from "vite";
import { defineConfig } from "vitest/config";

import { BRAND } from "./src/brand.ts";

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
    name: "coursejesus-route-documents",
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

/** The PWA manifest, generated from the same brand source as the documents. */
function brandManifest(): Record<string, unknown> {
  return {
    name: BRAND.name,
    short_name: BRAND.name,
    description: `${BRAND.name} — ${BRAND.tagline}`,
    lang: "en",
    start_url: "/",
    scope: "/",
    display: "standalone",
    theme_color: BRAND.themeColor,
    background_color: "#fffdf7",
    icons: [
      // The repository's existing mark. The owner's artwork will replace it and the
      // generated sizes/hashes will be added then; until that happens
      // `BRAND.logoStatus` says PENDING_ASSET rather than pretending otherwise.
      { src: BRAND.logoPath, sizes: "any", type: "image/svg+xml", purpose: "any" },
    ],
  };
}

/**
 * Replace the brand placeholders in every HTML entry, and serve/emit the manifest.
 *
 * A leftover placeholder is a hard build error: shipping a literal `%BRAND_NAME%`
 * to a user would be worse than failing the build.
 */
function brandDocuments(): Plugin {
  const manifest = JSON.stringify(brandManifest(), null, 2);
  const replacements: Record<string, string> = {
    "%BRAND_NAME%": BRAND.name,
    "%BRAND_NAME_ZH%": BRAND.nameZh,
    "%BRAND_TAGLINE%": BRAND.tagline,
    "%BRAND_CANONICAL%": BRAND.canonicalOrigin,
    "%BRAND_THEME_COLOR%": BRAND.themeColor,
    "%BRAND_LOGO%": BRAND.logoPath,
    "%BRAND_MANIFEST%": "/manifest.webmanifest",
  };
  return {
    name: "coursejesus-brand-documents",
    transformIndexHtml(html: string) {
      let output = html;
      for (const [placeholder, value] of Object.entries(replacements)) {
        output = output.split(placeholder).join(value);
      }
      const leftover = Object.keys(replacements).find((placeholder) => output.includes(placeholder));
      if (leftover) {
        throw new Error(`unreplaced brand placeholder ${leftover} in a document entry`);
      }
      return output;
    },
    configureServer(server: ViteDevServer) {
      server.middlewares.use((request, response, next) => {
        if ((request.url ?? "").split("?")[0] !== "/manifest.webmanifest") {
          next();
          return;
        }
        response.setHeader("Content-Type", "application/manifest+json");
        response.end(manifest);
      });
    },
    generateBundle() {
      this.emitFile({
        type: "asset",
        fileName: "manifest.webmanifest",
        source: manifest,
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), routeDocuments(), brandDocuments()],
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
    // `src` holds component tests and needs the DOM-only type environment of
    // tsconfig.app.json; `tests` holds repository-level guards that read the filesystem
    // and are typechecked by tsconfig.node.json instead.
    include: ["src/**/*.test.{ts,tsx}", "tests/**/*.test.ts"],
    restoreMocks: true,
    setupFiles: ["./src/test/setup.ts"],
    testTimeout: 15_000,
  },
});
