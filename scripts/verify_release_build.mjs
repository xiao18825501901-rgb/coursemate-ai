#!/usr/bin/env node
/**
 * Post-build verification for the production frontend publish path.
 *
 * Runs after `vite build` in the Netlify command. Non-production contexts are
 * a no-op. On a production deploy it:
 *
 *  - scans every published artifact for test identities and localhost API
 *    markers and fails the build on any hit;
 *  - writes build-info.json coupling the build environment summary, the release
 *    git SHA and the artifact hashes to this one build (the backend's
 *    production gate reads this marker file).
 */

import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";

const isProduction =
  process.env.CONTEXT === "production" || process.env.RELEASE_BUILD === "1";

if (!isProduction) {
  console.log("verify: non-production context, production verification skipped.");
  process.exit(0);
}

const distDir = path.resolve("apps/web/dist");
const failures = [];
const files = [];

function walk(dir) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(full);
    else files.push(full);
  }
}
walk(distDir);

const forbidden = [
  ["test-session-token", "test identity token"],
  ["TestAuthBridge", "test auth bridge"],
  ["VITE_AUTH_TEST_TOKEN", "test identity switch"],
  // Port-qualified localhost origins are baked API fallbacks; the bare
  // `http://localhost` template literal inside react-router's URL parser is
  // a library default and is deliberately not treated as an API origin.
  ["http://127.0.0.1:", "localhost API origin"],
  ["http://localhost:", "localhost API origin"],
  ["localhost:8000", "localhost API fallback"],
  ["localhost:8001", "localhost API fallback"],
  ["localhost:5273", "localhost API fallback"],
];

for (const file of files) {
  const content = readFileSync(file, "utf8");
  for (const [needle, label] of forbidden) {
    if (content.includes(needle)) {
      failures.push(`${path.relative(distDir, file)} contains ${label} marker "${needle}"`);
    }
  }
}

const assets = files.map((file) => {
  const bytes = readFileSync(file);
  return {
    file: path.relative(distDir, file),
    bytes: statSync(file).size,
    sha256: createHash("sha256").update(bytes).digest("hex").slice(0, 16),
  };
});

let gitSha = "unknown";
try {
  gitSha = execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8" }).trim();
} catch {
  gitSha = "unavailable";
}

const info = {
  built_at: new Date().toISOString(),
  context: process.env.CONTEXT ?? "production",
  not_for_production: false,
  clerk_publishable_key: {
    present: Boolean(process.env.VITE_CLERK_PUBLISHABLE_KEY),
    prefix: (process.env.VITE_CLERK_PUBLISHABLE_KEY ?? "").slice(0, 7),
    length: (process.env.VITE_CLERK_PUBLISHABLE_KEY ?? "").length,
  },
  api_origins: {
    ui: process.env.VITE_UI_API_BASE ?? "",
    rag: process.env.VITE_RAG_API_URL ?? "",
    agent: process.env.VITE_AGENT_API_URL ?? "",
  },
  release_sha: gitSha,
  artifacts: assets,
};
writeFileSync(path.join(distDir, "build-info.json"), JSON.stringify(info, null, 2) + "\n");

if (failures.length > 0) {
  console.error("Production artifact verification FAILED:");
  for (const failure of failures) console.error(`  - ${failure}`);
  process.exit(1);
}
console.log(`verify: ${assets.length} artifacts scanned, build-info.json written (sha ${gitSha}).`);
