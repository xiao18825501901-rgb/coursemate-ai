#!/usr/bin/env node
/**
 * Production READ-ONLY verification (no writes, no secrets).
 *
 * Scope requested from the user through the native approval channel:
 *   - reach the RAG / UI extension / Agent health endpoints over HTTPS;
 *   - confirm the published site serves the expected documents;
 *   - collect process/configuration NAMES the health endpoints expose.
 *
 * Explicitly NOT performed: any write, migration, restart, deploy, log download,
 * token/key/cookie reading or printing, and any paid model call.
 *
 * Without the production endpoints configured this script connects to nothing
 * and prints the missing-access report instead.
 */

const checks = [];

function env(name) {
  const value = process.env[name];
  return value && value.trim() ? value.trim() : undefined;
}

const rag = env("PROD_RAG_BASE_URL");
const agent = env("PROD_AGENT_BASE_URL");
const site = env("PROD_SITE_URL");

if (!rag) {
  console.log("PRODUCTION READ-ONLY CHECK: not executed - missing access.");
  console.log("Required environment (set only in a protected local/CI context):");
  console.log("  PROD_RAG_BASE_URL   e.g. https://rag.qqttai.com");
  console.log("  PROD_AGENT_BASE_URL e.g. https://agent.qqttai.com");
  console.log("  PROD_SITE_URL       e.g. https://www.qqttai.com  (or the site host)");
  console.log("No network request was made.");
  process.exit(2);
}

async function fetchStatus(url, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15_000);
  try {
    const response = await fetch(url, { ...options, signal: controller.signal, redirect: "manual" });
    return { url, status: response.status, bytes: null };
  } catch (error) {
    return { url, status: "unreachable", error: String(error).slice(0, 120) };
  } finally {
    clearTimeout(timer);
  }
}

async function main() {
  checks.push(await fetchStatus(`${rag}/health`));
  checks.push(await fetchStatus(`${rag}/ui-extension/health`));
  if (agent) checks.push(await fetchStatus(`${agent}/health`));
  if (site) checks.push(await fetchStatus(site));
  console.log("PRODUCTION READ-ONLY CHECK (masked summary; no secrets):");
  for (const check of checks) {
    console.log(`  ${check.url} -> ${check.status}${check.error ? ` (${check.error})` : ""}`);
  }
  console.log("Read-only check finished. No writes, no tokens, no paid calls.");
}

main();
