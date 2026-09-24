import { execFileSync } from "node:child_process";
import path from "node:path";

import { defineConfig } from "@playwright/test";

/**
 * Native-browser acceptance for the structured Jev enhancements that reach a real
 * business path (capability dispatch, and the "Jev unavailable" deployment).
 *
 * It runs the same real three-service shape as `playwright.ui.config.ts` — the RAG
 * API with the UI extension mounted, the existing Node task agent, and the
 * production web build behind the Netlify-shaped static server — because a module
 * only counts as integrated when the shipped shell really exercises it.
 */

const repositoryRoot = process.cwd();
const nodeExecutable = "C:\\Users\\Hp\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\node\\bin\\node.exe";
const pythonExecutable = path.join(repositoryRoot, "services", "rag-api", ".venv", "Scripts", "python.exe");
const chromeExecutable = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const e2eUserId = `jev-e2e-${process.pid}`;
const e2eData = path.join(repositoryRoot, "work", `e2e-jev-${process.pid}-${Date.now()}`);
const uiData = path.join(e2eData, "ui-extension");

execFileSync(
  pythonExecutable,
  [path.join(repositoryRoot, "scripts", "prepare_full_e2e.py"), e2eData, e2eUserId],
  { stdio: "inherit" },
);
execFileSync(
  pythonExecutable,
  [
    path.join(repositoryRoot, "scripts", "seed_legacy_conversation.py"),
    path.join(e2eData, "rag.sqlite3"),
    e2eUserId,
  ],
  { stdio: "inherit" },
);
execFileSync(
  pythonExecutable,
  [
    path.join(repositoryRoot, "scripts", "seed_tree_fixture.py"),
    path.join(e2eData, "rag.sqlite3"),
    e2eUserId,
  ],
  { stdio: "inherit" },
);
execFileSync(
  pythonExecutable,
  [
    path.join(repositoryRoot, "scripts", "seed_structured_fixture.py"),
    path.join(e2eData, "rag.sqlite3"),
    e2eUserId,
  ],
  { stdio: "inherit" },
);

export default defineConfig({
  testDir: "./tests/e2e",
  testMatch: "jev-structured.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  // A journey binds a node, sends a real teaching run and waits for it to reach a
  // terminal state through the mounted API.
  timeout: 180_000,
  expect: { timeout: 20_000 },
  use: {
    baseURL: "http://127.0.0.1:5273",
    browserName: "chromium",
    launchOptions: { executablePath: chromeExecutable },
    hasTouch: true,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: `"${pythonExecutable}" -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8100`,
      cwd: path.join(repositoryRoot, "services", "rag-api"),
      env: {
        ...process.env,
        RAG_PROVIDER_MODE: "deterministic",
        APP_ENV: "test",
        V3_ENABLED: "true",
        UI_EXTENSION_ENABLED: "true",
        CMUI_DATA_DIR: uiData,
        CMUI_PROVIDER_MODE: "test",
        CMUI_COVERAGE_REVIEWER: "deterministic",
        UI_TASK_AGENT_URL: "http://127.0.0.1:8101",
        CMUI_ALLOWED_ORIGINS: "http://127.0.0.1:5273",
        AUTH_TEST_USER_ID: e2eUserId,
        ADMIN_USER_IDS: "",
        WEB_ORIGIN: "http://127.0.0.1:5273",
        RAG_DATABASE_PATH: path.join(e2eData, "rag.sqlite3"),
        RAG_UPLOAD_DIR: path.join(e2eData, "uploads"),
        // The internal token the agent's tool-intent gate presents. Empty by
        // default, which leaves the endpoint answering 503 — the fail-closed
        // shape the "intent cannot be established" journey relies on.
        JEV_TOOL_INTENT_TOKEN: process.env.JEV_TOOL_INTENT_TOKEN ?? "",
        // Deliberately NO TypeSafe/Jev credential: this suite doubles as the
        // "Jev is unavailable" acceptance, which is the real production state.
        // A promotion run passes TYPESAFE_API_KEY and JEV_DEFINITION_MODES in the
        // environment instead of editing this file.
      },
      url: "http://127.0.0.1:8100/health",
      reuseExistingServer: false,
      timeout: 90_000,
      // Piped rather than ignored. A run of this suite with a live `TYPESAFE_API_KEY` in the
      // environment failed at the first UI step (`.workspace-columns` never appeared) and the
      // service's own log — the only thing that could say why — was being discarded, so the cause
      // was unknowable from the run. Playwright only prints piped output when the server fails to
      // start, so read it with `DEBUG=pw:webserver` (see the note in
      // DSH_JEV_DEEPSEEK_EXECUTION_STATE.md, round 86).
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      command: `"${nodeExecutable}" "${path.join(repositoryRoot, "services", "agent-api", "dist", "src", "server.js")}"`,
      cwd: repositoryRoot,
      env: {
        ...process.env,
        AGENT_DATABASE_PATH: path.join(e2eData, "agent.sqlite3"),
        AGENT_PROVIDER_MODE: "deterministic",
        NODE_ENV: "test",
        AUTH_TEST_USER_ID: e2eUserId,
        AGENT_PORT: "8101",
        WEB_ORIGIN: "http://127.0.0.1:5273",
        // The side-effecting tool boundary (module F). `off` by default, so the
        // committed shape puts no gate in front of a write; the journeys that prove
        // the guard skip with that reason unless the environment turns it on, and
        // the agent refuses to start with a mode other than `off` without a URL and
        // a token, so the three are passed through together.
        JEV_TOOL_INTENT_MODE: process.env.JEV_TOOL_INTENT_MODE ?? "off",
        JEV_TOOL_INTENT_URL: process.env.JEV_TOOL_INTENT_URL ?? "",
        JEV_TOOL_INTENT_TOKEN: process.env.JEV_TOOL_INTENT_TOKEN ?? "",
        // The guard's own budget, in milliseconds (the agent bounds it to 100–10 000).
        // Passed through because the measured live decision takes 0.68–1.35 s against
        // a 1.5 s default: leaving it unset would measure the timeout, not the verdict.
        // `|| "1500"` and not `?? "1500"`: an *empty* value is rejected by the agent
        // ("Expected an integer between 100 and 10000") and it refuses to start, which
        // is how a passthrough of "" took the whole suite down while every service
        // looked healthy. (PowerShell deletes an env var assigned "", so checking this
        // by hand in the shell does not reproduce it — the config really does pass "".)
        JEV_TOOL_INTENT_TIMEOUT_MS: process.env.JEV_TOOL_INTENT_TIMEOUT_MS || "1500",
      },
      url: "http://127.0.0.1:8101/health",
      reuseExistingServer: false,
      timeout: 90_000,
      stdout: "ignore",
      stderr: "ignore",
    },
    {
      command: `"${nodeExecutable}" "${path.join(repositoryRoot, "scripts", "serve_web_dist.mjs")}" "${path.join(repositoryRoot, "apps", "web", "dist")}" 5273`,
      cwd: repositoryRoot,
      env: {
        ...process.env,
        COURSEMATE_API_PROXY: "http://127.0.0.1:8100",
      },
      url: "http://127.0.0.1:5273/app",
      reuseExistingServer: false,
      timeout: 90_000,
      stdout: "ignore",
      stderr: "ignore",
    },
    {
      // The shipped *legacy* pages resolve the RAG API from the value baked into
      // the build (`localhost:8000`), while the refreshed shell uses same-origin
      // `/api` through the proxy above. The module-A journey drives the legacy QA
      // page — the one shipped surface whose own request stream carries the
      // reference-verification report — so the same build output is served once
      // more on that baked origin, proxying to the same backend. No product or
      // release artifact is involved: this is the local acceptance deployment only.
      command: `"${nodeExecutable}" "${path.join(repositoryRoot, "scripts", "serve_web_dist.mjs")}" "${path.join(repositoryRoot, "apps", "web", "dist")}" 8000`,
      cwd: repositoryRoot,
      env: {
        ...process.env,
        COURSEMATE_API_PROXY: "http://127.0.0.1:8100",
      },
      url: "http://127.0.0.1:8000/",
      reuseExistingServer: false,
      timeout: 90_000,
      stdout: "ignore",
      stderr: "ignore",
    },
  ],
});
