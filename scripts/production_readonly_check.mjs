#!/usr/bin/env node
/**
 * Production READ-ONLY verification (no writes, no secrets, no identity).
 *
 * Approved scope (user consent for public endpoints only):
 *   GET https://rag.qqttai.com/health
 *   GET https://rag.qqttai.com/ui-extension/health
 *   GET https://agent.qqttai.com/health
 *   GET https://qqttai.com/
 *
 * Behavior: TLS verification on, no Authorization/Cookie, manual redirects
 * (a 3xx is reported, never followed to unknown hosts), one attempt per URL,
 * 15s timeout, no retries. Every observation records the timestamp, elapsed
 * time, HTTP status, Content-Type and a bounded, non-sensitive body summary.
 * Nothing is written to disk and no secret can ever appear in the output.
 */

const requests = [];

function env(name) {
  const value = process.env[name];
  return value && value.trim() ? value.trim() : undefined;
}

const targets = [
  { label: "rag_health", url: env("PROD_RAG_BASE_URL") && `${env("PROD_RAG_BASE_URL").replace(/\/+$/, "")}/health` },
  { label: "ui_extension_health", url: env("PROD_RAG_BASE_URL") && `${env("PROD_RAG_BASE_URL").replace(/\/+$/, "")}/ui-extension/health` },
  { label: "agent_health", url: env("PROD_AGENT_BASE_URL") && `${env("PROD_AGENT_BASE_URL").replace(/\/+$/, "")}/health` },
  { label: "site_root", url: env("PROD_SITE_URL") },
].filter((target) => target.url);

if (targets.length === 0) {
  console.log("PRODUCTION READ-ONLY CHECK: not executed - missing access.");
  console.log("Set PROD_RAG_BASE_URL / PROD_AGENT_BASE_URL / PROD_SITE_URL (public");
  console.log("addresses only) in the process environment. No request was made.");
  process.exit(2);
}

function stageOf(error) {
  const name = String(error?.name ?? "");
  const cause = String(error?.cause?.code ?? error?.code ?? "");
  if (name === "TimeoutError" || cause === "UND_ERR_CONNECT_TIMEOUT" || /timeout/i.test(name)) return "timeout";
  if (/getaddrinfo|ENOTFOUND|EAI_AGAIN/i.test(cause)) return "dns";
  if (/CERT_|UNABLE_TO_VERIFY|self.signed|ERR_TLS/i.test(String(error?.cause?.message ?? "")) || /TLS/i.test(String(error?.message ?? ""))) return "tls";
  if (/ECONNREFUSED|ECONNRESET|socket hang up|UND_ERR_SOCKET|fetch failed/i.test(cause + " " + String(error?.message ?? ""))) return "connect";
  return "transport";
}

function summaryOf(contentType, body) {
  if (!body) return "";
  const text = body.slice(0, 600);
  if (contentType && contentType.includes("application/json")) {
    return text.replace(/\s+/g, " ").slice(0, 240);
  }
  // Document shape only: which document the site serves, no page content.
  const htmlTitle = /<title[^>]*>([^<]{0,120})/.exec(text);
  const marker = /assets\/(ui|main)-[\w-]+\.js/.exec(text);
  const loginHint = text.includes("Authentication is not configured")
    ? "auth_not_configured_page"
    : text.includes("登录") || text.includes("sign in") || text.includes("SignIn")
      ? "login_page"
      : "";
  return `title=${htmlTitle ? htmlTitle[1].slice(0, 80) : "n/a"} bundle=${marker ? marker[1] : "n/a"} shape=${loginHint || "n/a"}`;
}

async function observe(target) {
  const started = new Date().toISOString();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15_000);
  try {
    const response = await fetch(target.url, {
      method: "GET",
      signal: controller.signal,
      redirect: "manual",
    });
    const contentType = response.headers.get("content-type") ?? "";
    const body = await response.text();
    return {
      label: target.label,
      url: target.url,
      started_at_utc: started,
      finished_at_utc: new Date().toISOString(),
      status: response.status,
      content_type: contentType,
      summary: summaryOf(contentType, body),
      error_stage: null,
    };
  } catch (error) {
    return {
      label: target.label,
      url: target.url,
      started_at_utc: started,
      finished_at_utc: new Date().toISOString(),
      status: null,
      content_type: null,
      summary: "",
      error_stage: stageOf(error),
    };
  } finally {
    clearTimeout(timer);
  }
}

async function main() {
  console.log("PRODUCTION READ-ONLY CHECK (public endpoints, no identity, TLS on, no redirect follow):");
  for (const target of targets) {
    const observation = await observe(target);
    requests.push(observation);
    const line = [
      observation.started_at_utc,
      observation.url,
      observation.status === null ? `status=NONE(${observation.error_stage})` : `status=${observation.status}`,
      observation.content_type ? `type=${observation.content_type}` : "",
      observation.summary ? `summary=${observation.summary}` : "",
    ].filter(Boolean).join(" ");
    console.log(`  ${line}`);
  }
  console.log("Finished. One attempt per URL, no writes, no tokens, no paid calls.");
}

main();
