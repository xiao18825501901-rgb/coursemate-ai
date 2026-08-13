import path from "node:path";

import { defineConfig } from "@playwright/test";


const repositoryRoot = process.cwd();
const nodeExecutable = "C:\\Users\\Hp\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\node\\bin\\node.exe";
const pythonExecutable = path.join(repositoryRoot, "services", "rag-api", ".venv", "Scripts", "python.exe");
const chromeExecutable = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const e2eUserId = `e2e-user-${process.pid}`;

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  expect: { timeout: 15_000 },
  use: {
    baseURL: "http://127.0.0.1:5173",
    browserName: "chromium",
    launchOptions: { executablePath: chromeExecutable },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: `"${pythonExecutable}" -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000`,
      cwd: path.join(repositoryRoot, "services", "rag-api"),
      env: {
        ...process.env,
        RAG_PROVIDER_MODE: "deterministic",
        APP_ENV: "test",
        AUTH_TEST_USER_ID: e2eUserId,
        ADMIN_USER_IDS: "",
        WEB_ORIGIN: "http://127.0.0.1:5173",
      },
      url: "http://127.0.0.1:8000/health",
      reuseExistingServer: false,
      timeout: 60_000,
      stdout: "ignore",
      stderr: "ignore",
    },
    {
      command: `"${nodeExecutable}" "${path.join(repositoryRoot, "services", "agent-api", "dist", "src", "server.js")}"`,
      cwd: repositoryRoot,
      env: {
        ...process.env,
        AGENT_DATABASE_PATH: path.join(repositoryRoot, "work", `e2e-agent-${process.pid}.sqlite3`),
        AGENT_PROVIDER_MODE: "deterministic",
        NODE_ENV: "test",
        AUTH_TEST_USER_ID: e2eUserId,
        AGENT_PORT: "8001",
        WEB_ORIGIN: "http://127.0.0.1:5173",
      },
      url: "http://127.0.0.1:8001/health",
      reuseExistingServer: false,
      timeout: 60_000,
      stdout: "ignore",
      stderr: "ignore",
    },
    {
      command: `"${nodeExecutable}" "${path.join(repositoryRoot, "node_modules", "vite", "bin", "vite.js")}" --host 127.0.0.1`,
      cwd: path.join(repositoryRoot, "apps", "web"),
      env: {
        ...process.env,
        VITE_RAG_API_URL: "http://127.0.0.1:8000",
        VITE_AGENT_API_URL: "http://127.0.0.1:8001",
        VITE_AUTH_TEST_TOKEN: "test-session-token",
      },
      url: "http://127.0.0.1:5173",
      reuseExistingServer: false,
      timeout: 60_000,
      stdout: "ignore",
      stderr: "ignore",
    },
  ],
});
