#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import process from "node:process";


const OLD_ORIGIN = "https://qqttai.com";
const NEW_ORIGIN = "https://coursejesus.com";
const UNKNOWN_ORIGIN = "https://evil.example";
const NETWORK_ENABLED = process.argv.includes("--network");

function parseOrigins(raw, primary) {
  const origins = [];
  for (const item of (raw ?? "").split(",")) {
    const origin = item.trim();
    if (origin && !origins.includes(origin)) origins.push(origin);
  }
  if (primary && !origins.includes(primary)) origins.push(primary);
  return origins;
}

function sourceSha() {
  const result = spawnSync("git", ["rev-parse", "HEAD"], {
    encoding: "utf8",
    windowsHide: true,
  });
  if (result.status !== 0) throw new Error("Unable to read the current source SHA.");
  return result.stdout.trim();
}

function requireMigrationOrigins(name, origins) {
  for (const expected of [OLD_ORIGIN, NEW_ORIGIN]) {
    if (!origins.includes(expected)) {
      throw new Error(`${name} does not include ${expected}.`);
    }
  }
}

function exactHttpsBaseUrl(name, raw) {
  if (!raw) throw new Error(`${name} is required with --network.`);
  const parsed = new URL(raw);
  if (
    parsed.protocol !== "https:" ||
    parsed.origin !== raw ||
    parsed.username ||
    parsed.password ||
    parsed.search ||
    parsed.hash
  ) {
    throw new Error(`${name} must be an exact HTTPS origin.`);
  }
  return parsed.origin;
}

async function fetchReadOnly(url, init = {}) {
  const response = await fetch(url, {
    ...init,
    redirect: "manual",
    signal: AbortSignal.timeout(10_000),
  });
  return {
    status: response.status,
    allowOrigin: response.headers.get("access-control-allow-origin"),
    contentType: response.headers.get("content-type"),
  };
}

async function checkService(name, baseUrl) {
  const health = await fetchReadOnly(`${baseUrl}/health`, { method: "GET" });
  if (health.status !== 200) throw new Error(`${name} health returned ${health.status}.`);
  console.log(`${name} health status=${health.status} type=${health.contentType ?? "n/a"}`);

  for (const origin of [OLD_ORIGIN, NEW_ORIGIN]) {
    const preflight = await fetchReadOnly(`${baseUrl}/health`, {
      method: "OPTIONS",
      headers: {
        Origin: origin,
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "authorization",
      },
    });
    if (preflight.allowOrigin !== origin) {
      throw new Error(`${name} did not allow the expected origin ${origin}.`);
    }
    console.log(`${name} CORS origin=${origin} status=${preflight.status} allowed=yes`);
  }

  const unknown = await fetchReadOnly(`${baseUrl}/health`, {
    method: "OPTIONS",
    headers: {
      Origin: UNKNOWN_ORIGIN,
      "Access-Control-Request-Method": "GET",
      "Access-Control-Request-Headers": "authorization",
    },
  });
  if (unknown.allowOrigin !== null) {
    throw new Error(`${name} unexpectedly allowed ${UNKNOWN_ORIGIN}.`);
  }
  console.log(`${name} CORS origin=${UNKNOWN_ORIGIN} status=${unknown.status} allowed=no`);
}

async function main() {
  const webOrigin = (process.env.WEB_ORIGIN ?? "").trim();
  const webAllowedOrigins = parseOrigins(process.env.WEB_ALLOWED_ORIGINS, webOrigin);
  const cmuiAllowedOrigins = parseOrigins(process.env.CMUI_ALLOWED_ORIGINS, "");

  if (webOrigin !== OLD_ORIGIN && webOrigin !== NEW_ORIGIN) {
    throw new Error("WEB_ORIGIN must be the old or new canonical migration origin.");
  }
  requireMigrationOrigins("WEB_ALLOWED_ORIGINS", webAllowedOrigins);
  requireMigrationOrigins("CMUI_ALLOWED_ORIGINS", cmuiAllowedOrigins);

  console.log(`source_sha=${sourceSha()}`);
  console.log(`WEB_ORIGIN=${webOrigin}`);
  console.log(`WEB_ALLOWED_ORIGINS=${webAllowedOrigins.join(",")}`);
  console.log(`CMUI_ALLOWED_ORIGINS=${cmuiAllowedOrigins.join(",")}`);
  console.log("secrets=not-read");

  if (!NETWORK_ENABLED) {
    console.log("network_checks=skipped (add --network with explicit base URLs)");
    return;
  }

  const ragBaseUrl = exactHttpsBaseUrl("RAG_BASE_URL", process.env.RAG_BASE_URL);
  const agentBaseUrl = exactHttpsBaseUrl("AGENT_BASE_URL", process.env.AGENT_BASE_URL);
  await checkService("RAG", ragBaseUrl);
  await checkService("Agent", agentBaseUrl);
  console.log("network_methods=GET,OPTIONS only; database_writes=none; model_calls=none");
}

main().catch((error) => {
  console.error(`readiness_check_failed=${error instanceof Error ? error.message : String(error)}`);
  process.exitCode = 1;
});
