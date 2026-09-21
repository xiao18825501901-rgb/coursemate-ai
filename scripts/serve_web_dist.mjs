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
 *
 * In production Netlify also proxies the API on the same origin, which is what the
 * refreshed shell relies on (`/api/ui/v1` with no absolute host). Set
 * `COURSEMATE_API_PROXY=http://127.0.0.1:8100` (or any base URL) to reproduce that
 * here: `/api/*` and `/health*` are then forwarded to the target, and every other
 * path keeps the static behaviour above. With the variable unset nothing changes,
 * so other callers of this script are unaffected.
 */

import { createReadStream, existsSync, statSync } from "node:fs";
import { createServer, request as httpRequest } from "node:http";
import { request as httpsRequest } from "node:https";
import path from "node:path";

const root = path.resolve(process.argv[2] ?? "apps/web/dist");
const port = Number(process.argv[3] ?? 5273);
const proxyTarget = (process.env.COURSEMATE_API_PROXY ?? "").trim();
// `/api` is the deployed shape; `/ui-extension` is the RAG service's own mount path
// for the UI extension, which is where the shell's API base points by default.
const PROXY_PREFIXES = ["/api", "/ui-extension", "/health"];

function shouldProxy(pathname) {
  if (proxyTarget === "") return false;
  return PROXY_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}

function forward(request, response, pathname, search) {
  let target;
  try {
    target = new URL(proxyTarget);
  } catch {
    response.writeHead(500, { "Content-Type": "text/plain; charset=utf-8" });
    response.end(`Invalid COURSEMATE_API_PROXY: ${proxyTarget}\n`);
    return;
  }
  const base = target.pathname.replace(/\/$/, "");
  const send = target.protocol === "https:" ? httpsRequest : httpRequest;
  const upstream = send(
    {
      protocol: target.protocol,
      hostname: target.hostname,
      port: target.port,
      method: request.method,
      path: `${base}${pathname}${search}`,
      headers: { ...request.headers, host: target.host },
    },
    (upstreamResponse) => {
      response.writeHead(upstreamResponse.statusCode ?? 502, upstreamResponse.headers);
      upstreamResponse.pipe(response);
    },
  );
  upstream.on("error", (error) => {
    // Fail loudly and machine-readably: a browser test must never mistake a dead
    // upstream for a successful API answer.
    response.writeHead(502, { "Content-Type": "application/json; charset=utf-8" });
    response.end(JSON.stringify({ error: "proxy_failed", target: proxyTarget, detail: error.message }));
  });
  request.pipe(upstream);
}

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

  if (shouldProxy(pathname)) {
    forward(request, response, pathname, url.search);
    return;
  }

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
