#!/usr/bin/env node
/**
 * Live canary C1+C2 driver (isolated environment, real Qwen calls).
 *
 * C1: one full two-stage free-text teaching (Word-template prompt -> teaching).
 * C2: the same completed teaching reviewed by the model coverage reviewer and
 *     submitted as real coverage, observed from zero on a seeded node with two
 *     REQUIRED items.
 *
 * Environment: the credential is read from V3_MODEL_API_KEY / V3_MODEL_BASE_URL
 * (or CMUI_QWEN_API_KEY / CMUI_QWEN_BASE_URL) - never printed. Everything runs
 * against an isolated copy of the local dev database under work/canary-*, with
 * a synthetic test user. No production data is touched.
 *
 * Budget: the approved whole-batch cap is CNY 5.00 with a C1+C2 stage cap of
 * CNY 1.50 (estimated at the Singapore International list prices; the actual
 * account bill is reconciled afterwards). If the estimated spend crosses the
 * stage cap the driver stops before starting further stages.
 */

import { execFileSync, spawn } from "node:child_process";
import { copyFileSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";

const ROOT = process.cwd();
const PY = path.join(ROOT, "services/rag-api/.venv/Scripts/python.exe");
const STAGE_CAP_CNY = 1.5;
const IN_CNY_PER_1M = 14.988; // Singapore International list price (input)
const OUT_CNY_PER_1M = 44.965; // Singapore International list price (output)
const PORT = 8107;
const USER = "canary-user";

function env(name) {
  const value = process.env[name];
  return value && value.trim() ? value.trim() : undefined;
}

const apiKey = env("V3_MODEL_API_KEY") || env("CMUI_QWEN_API_KEY");
const baseUrl = env("V3_MODEL_BASE_URL") || env("CMUI_QWEN_BASE_URL");

if (!apiKey || !baseUrl) {
  console.error("Canary blocked: the site Qwen credential is not on this machine.");
  console.error("Place it in the protected local mechanism (gitignored):");
  console.error("  services/rag-api/.env");
  console.error("    V3_MODEL_API_KEY=sk-...        (never paste it into chat)");
  console.error("    V3_MODEL_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1");
  console.error("Then re-run: node scripts/run_canary_c1c2.mjs");
  process.exit(2);
}

const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const canaryDir = path.join(ROOT, "work", `canary-${stamp}`);
mkdirSync(canaryDir, { recursive: true });
const dbPath = path.join(canaryDir, "rag.sqlite3");
const uiData = path.join(canaryDir, "ui");
const evidencePath = path.join(canaryDir, "canary-evidence.json");

const sourceDb = path.join(ROOT, "data/rag.sqlite3");
if (!existsSync(sourceDb)) {
  console.error("Local dev database data/rag.sqlite3 is missing; cannot build the isolated copy.");
  process.exit(2);
}
copyFileSync(sourceDb, dbPath);
execFileSync(PY, [path.join(ROOT, "scripts/seed_canary_node.py"), dbPath, USER], { stdio: "inherit" });

const server = spawn(
  PY,
  ["-m", "uvicorn", "app.main:create_app", "--factory", "--host", "127.0.0.1", "--port", String(PORT)],
  {
    cwd: path.join(ROOT, "services/rag-api"),
    env: {
      ...process.env,
      V3_MODEL_API_KEY: apiKey,
      V3_MODEL_BASE_URL: baseUrl,
      RAG_PROVIDER_MODE: "deterministic",
      APP_ENV: "test",
      V3_ENABLED: "true",
      UI_EXTENSION_ENABLED: "true",
      CMUI_DATA_DIR: uiData,
      CMUI_PROVIDER_MODE: "qwen",
      CMUI_ALLOW_BILLABLE: "true",
      CMUI_COVERAGE_REVIEWER: "model",
      AUTH_TEST_USER_ID: USER,
      ADMIN_USER_IDS: "",
      WEB_ORIGIN: `http://127.0.0.1:${PORT}`,
      CMUI_ALLOWED_ORIGINS: `http://127.0.0.1:${PORT}`,
      RAG_DATABASE_PATH: dbPath,
      RAG_UPLOAD_DIR: path.join(canaryDir, "uploads"),
    },
    stdio: ["ignore", "pipe", "pipe"],
  },
);

const api = `http://127.0.0.1:${PORT}/ui-extension/api/ui/v1`;
const headers = { Authorization: "Bearer test-session-token", "Content-Type": "application/json" };
const evidence = {
  started_at_utc: new Date().toISOString(),
  environment: "isolated local copy under work/, synthetic user, no production writes",
  model: "qwen3.8-max",
  stage_cap_cny: STAGE_CAP_CNY,
  whole_batch_cap_cny: 5.0,
  price_table_cny_per_1m: { input: IN_CNY_PER_1M, output: OUT_CNY_PER_1M, source: "official list, Singapore International; reconcile with account bill" },
  steps: [],
};

async function jsonFetch(url, options = {}) {
  const response = await fetch(url, { ...options, headers: { ...headers, ...(options.headers ?? {}) } });
  const body = await response.json().catch(() => null);
  return { status: response.status, body };
}

async function waitHealth() {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    try {
      const response = await fetch(`http://127.0.0.1:${PORT}/health`);
      if (response.status === 200) return;
    } catch {
      /* still starting */
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error("canary backend did not become healthy in 120s");
}

async function waitRun(runId) {
  for (let attempt = 0; attempt < 300; attempt += 1) {
    const { body } = await jsonFetch(`${api}/runs/${runId}`);
    if (body && ["completed", "failed", "cancelled"].includes(body.status)) return body;
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error(`run ${runId} did not finish in 300s`);
}

function usageOf(run) {
  const usage = run.usage ?? [];
  let input = 0;
  let output = 0;
  for (const entry of usage) {
    const value = entry.value ?? {};
    input += Number(value.prompt_tokens ?? value.input_tokens ?? 0);
    output += Number(value.completion_tokens ?? value.output_tokens ?? 0);
  }
  return { input, output, estimated_cny: (input / 1e6) * IN_CNY_PER_1M + (output / 1e6) * OUT_CNY_PER_1M };
}

function stop(reason) {
  console.log(`STOP: ${reason}`);
  server.kill();
  writeFileSync(evidencePath, JSON.stringify(evidence, null, 2) + "\n");
  process.exit(reason.startsWith("STAGE_CAP") ? 3 : reason.startsWith("FAIL") ? 1 : 0);
}

async function main() {
  let serverOutput = "";
  server.stdout.on("data", (chunk) => { serverOutput += String(chunk); });
  server.stderr.on("data", (chunk) => { serverOutput += String(chunk); });
  await waitHealth();
  evidence.steps.push({ step: "backend_healthy", at: new Date().toISOString() });

  // C1+C2: one teaching run on the zero-coverage node; the model reviewer runs
  // on the saved body and the coverage submission follows.
  const conversation = await jsonFetch(`${api}/conversations`, {
    method: "POST",
    body: JSON.stringify({ course: "cs3481", lane: "teach" }),
  });
  const question =
    "请用中文讲解 DBSCAN 如何用密度条件识别核心点，以及聚类如何从核心点扩张；保留英文术语，结合定义和判断边界点的规则。";
  const started = await jsonFetch(
    `${api}/conversations/${conversation.body.id}/runs`,
    {
      method: "POST",
      body: JSON.stringify({
        text: question,
        request_id: `canary-c1c2-${stamp}`,
        node_id: "canary-clustering-zero",
      }),
    },
  );
  if (started.status !== 202) stop(`FAIL run start: ${started.status} ${JSON.stringify(started.body)}`);
  const run = await waitRun(started.body.id);
  const usage = usageOf(run);
  evidence.steps.push({
    step: "teach_run",
    run_id: run.id,
    status: run.status,
    error: run.error ?? null,
    usage,
    generated_prompt_chars: (run.generated_prompt ?? "").length,
    prompt_sample_head: String(run.generated_prompt ?? "").slice(0, 500),
    answer_sample_head: String(run.partial_text ?? "").slice(0, 500),
    coverage_receipt: run.coverage ?? null,
  });
  if (usage.estimated_cny > STAGE_CAP_CNY) stop(`STAGE_CAP exceeded: ${usage.estimated_cny.toFixed(4)} CNY`);

  const knowledge = await jsonFetch(`${api}/courses/cs3481/knowledge`);
  const node = (knowledge.body ?? []).find((row) => row.id === "canary-clustering-zero");
  evidence.steps.push({
    step: "coverage_state",
    progress: node?.progress ?? null,
    learning: node?.learning ?? null,
    assessment: node?.assessment?.status ?? null,
  });

  evidence.finished_at_utc = new Date().toISOString();
  evidence.server_log_tail = serverOutput.slice(-2000);
  writeFileSync(evidencePath, JSON.stringify(evidence, null, 2) + "\n");
  console.log(`C1+C2 finished. run=${run.id} status=${run.status} usage=${JSON.stringify(usage)}`);
  console.log(`node progress=${node?.progress} covered=${node?.learning?.covered_required}/${node?.learning?.required_total}`);
  console.log(`evidence: ${evidencePath}`);
  server.kill();
  process.exit(run.status === "completed" ? 0 : 1);
}

main().catch((error) => stop(`FAIL ${String(error)}`));
