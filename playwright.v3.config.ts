import { execFileSync } from "node:child_process";
import path from "node:path";
import { defineConfig } from "@playwright/test";

const root = process.cwd();
const python = path.join(root, "services/rag-api/.venv/Scripts/python.exe");
const data = path.join(root, "work", `v3-e2e-${process.pid}-${Date.now()}`);
execFileSync(python, [path.join(root, "scripts/prepare_v3_e2e.py"), data]);

export default defineConfig({
  testDir: "./tests/e2e", testMatch: "learning.spec.ts", workers: 1, retries: 0,
  reporter: [["list"]], expect: { timeout: 15000 },
  use: { baseURL: "http://127.0.0.1:15173", browserName: "chromium",
    launchOptions: { executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe" },
    screenshot: "only-on-failure", trace: "retain-on-failure" },
  webServer: [
    { command: `"${python}" -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 18100`,
      cwd: path.join(root, "services/rag-api"),
      env: { ...process.env, APP_ENV: "test", RAG_PROVIDER_MODE: "deterministic", V3_ENABLED: "true",
        AUTH_TEST_USER_ID: "v3-e2e-owner", ADMIN_USER_IDS: "", WEB_ORIGIN: "http://127.0.0.1:15173",
        RAG_DATABASE_PATH: path.join(data, "rag.db"), RAG_UPLOAD_DIR: path.join(data, "uploads") },
      url: "http://127.0.0.1:18100/health", reuseExistingServer: false, timeout: 60000 },
    { command: `"${process.execPath}" "${path.join(root, "node_modules/vite/bin/vite.js")}" --host 127.0.0.1 --port 15173`,
      cwd: path.join(root, "apps/web"),
      env: { ...process.env, VITE_RAG_API_URL: "http://127.0.0.1:18100", VITE_V3_ENABLED: "true",
        VITE_AUTH_TEST_TOKEN: "test-session-token" },
      url: "http://127.0.0.1:15173", reuseExistingServer: false, timeout: 60000 },
  ],
});
