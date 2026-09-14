#!/usr/bin/env node
/**
 * Serve the production web build with the same routing Netlify applies.
 *
 * The document decision mirrors `netlify.toml` exactly:
 *   "/" and unknown paths → ui.html (the refreshed shell is the default entry)
 *   "/app", "/app/*"      → ui.html (compatibility alias)
 *   legacy deep links    → index.html (previous site stays reachable)
 *
 * Deployed asset files are served directly and never rewritten, matching Netlify.
 * This server exists so the browser acceptance suite exercises the real build
 * output and the real URL shapes rather than the Vite development server.
 */

import { createReadStream, existsSync, statSync } from "node:fs";
import { createServer } from "node:http";
import path from "node:path";

const root = path.resolve(process.argv[2] ?? "apps/web/dist");
const port = Number(process.argv[3] ?? 5273);

const TYPES = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".ico": "image/x-icon",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".map": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".woff2": "font/woff2",
};

const LEGACY_PREFIXES = ["qa", "learn", "courses", "tasks", "documents", "admin", "about"];

/**
 * First path segment of a URL. "/qa/cs3481" → "qa", "/app" → "app", "/" → "".
 */
function firstSegment(pathname) {
  const parts = pathname.split("/").filter(Boolean);
  return parts[0] ?? "";
}

/**
 * Same decision table as `netlify.toml`; keep them in sync.
 */
export function documentFor(pathname) {
  if (pathname === "/" || pathname === "") return "ui.html";
  if (pathname === "/app" || pathname.startsWith("/app/")) return "ui.html";
  if (LEGACY_PREFIXES.includes(firstSegment(pathname))) return "index.html";
  return "ui.html";
}

const server = createServer((request, response) => {
  const url = new URL(request.url ?? "/", `http://127.0.0.1:${port}`);
  const pathname = decodeURIComponent(url.pathname);
  const direct = path.join(root, pathname);
  const isInsideRoot = direct.startsWith(root);

  if (isInsideRoot && pathname !== "/" && existsSync(direct) && statSync(direct).isFile()) {
    response.writeHead(200, {
      "Content-Type": TYPES[path.extname(direct)] ?? "application/octet-stream",
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
    });
    createReadStream(direct).pipe(response);
    return;
  }

  const fallback = path.join(root, documentFor(pathname));
  if (!existsSync(fallback)) {
    response.writeHead(500, { "Content-Type": "text/plain; charset=utf-8" });
    response.end(`Missing build output: ${fallback}\n`);
    return;
  }
  response.writeHead(200, {
    "Content-Type": "text/html; charset=utf-8",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
  });
  createReadStream(fallback).pipe(response);
});

server.listen(port, "127.0.0.1", () => {
  process.stdout.write(`serving ${root} at http://127.0.0.1:${port}\n`);
});
