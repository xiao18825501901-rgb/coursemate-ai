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
        // Deliberately NO TypeSafe/Jev credential: this suite doubles as the
        // "Jev is unavailable" acceptance, which is the real production state.
      },
      url: "http://127.0.0.1:8100/health",
      reuseExistingServer: false,
      timeout: 90_000,
      stdout: "ignore",
      stderr: "ignore",
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
  ],
});
