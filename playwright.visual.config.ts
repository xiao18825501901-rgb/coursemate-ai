import { execFileSync } from "node:child_process";
import path from "node:path";

import { defineConfig } from "@playwright/test";

const root = process.cwd();
const node = process.execPath;
const python = path.join(root, "services", "rag-api", ".venv", "Scripts", "python.exe");
const chrome = process.env.PLAYWRIGHT_CHROME_PATH || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const user = `visual-e2e-${process.pid}`;
const data = path.join(root, "work", `e2e-visual-${process.pid}-${Date.now()}`);
const webDist = path.join(data, "web-dist");

execFileSync(python, [path.join(root, "scripts", "prepare_full_e2e.py"), data, user], {
  stdio: "inherit",
});
execFileSync(
  node,
  [
    path.join(root, "apps", "web", "node_modules", "vite", "bin", "vite.js"),
    "build",
    "--outDir",
    webDist,
  ],
  {
    cwd: path.join(root, "apps", "web"),
    env: { ...process.env, VITE_AUTH_TEST_TOKEN: "test-session-token" },
    stdio: "inherit",
  },
);

export default defineConfig({
  testDir: "./tests/e2e",
  testMatch: "visual-learning.spec.ts",
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  timeout: 90_000,
  expect: { timeout: 20_000 },
  use: {
    baseURL: "http://127.0.0.1:5373",
    browserName: "chromium",
    launchOptions: { executablePath: chrome },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: `"${python}" -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8300`,
      cwd: path.join(root, "services", "rag-api"),
      env: {
        ...process.env,
        RAG_PROVIDER_MODE: "deterministic",
        APP_ENV: "test",
        CMUI_ENV: "test",
        V3_ENABLED: "true",
        UI_EXTENSION_ENABLED: "true",
        VISUAL_ENGINE_ENABLED: "true",
        VISUAL_PROVIDER: "mock",
        CMUI_DATA_DIR: path.join(data, "ui-extension"),
        CMUI_PROVIDER_MODE: "test",
        CMUI_ALLOWED_ORIGINS: "http://127.0.0.1:5373",
        AUTH_TEST_USER_ID: user,
        WEB_ORIGIN: "http://127.0.0.1:5373",
        RAG_DATABASE_PATH: path.join(data, "rag.sqlite3"),
        RAG_UPLOAD_DIR: path.join(data, "uploads"),
      },
      url: "http://127.0.0.1:8300/health",
      reuseExistingServer: false,
      timeout: 90_000,
    },
    {
      command: `"${node}" "${path.join(root, "scripts", "serve_web_dist.mjs")}" "${webDist}" 5373`,
      cwd: root,
      env: { ...process.env, COURSEMATE_API_PROXY: "http://127.0.0.1:8300" },
      url: "http://127.0.0.1:5373/app",
      reuseExistingServer: false,
      timeout: 90_000,
    },
  ],
});
