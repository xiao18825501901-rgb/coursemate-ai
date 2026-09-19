import { execFileSync } from "node:child_process";
import path from "node:path";
import { defineConfig } from "@playwright/test";

const root = process.cwd();
const python = path.join(root, "work/codex-audit/venv/Scripts/python.exe");
const node = process.execPath;
const inheritedRun = process.env.CODEX_AUDIT_RUN_DIR;
const run = inheritedRun || path.join(root, "work/codex-audit", `browser-${Date.now()}-${process.pid}`);
process.env.CODEX_AUDIT_RUN_DIR = run;
// Do not forward account credentials, provider endpoints, or live environment files.
const env: Record<string,string> = {};
for (const key of ["PATH", "Path", "SystemRoot", "WINDIR", "TEMP", "TMP", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "COMSPEC"])
  if (process.env[key]) env[key] = process.env[key]!;
const safeEnv = {
  ...env, CODEX_AUDIT_RUN_DIR: run, APP_ENV: "test", RAG_PROVIDER_MODE: "deterministic",
  V3_ENABLED: "true", UI_EXTENSION_ENABLED: "true", CMUI_ENV: "test",
  CMUI_DATA_DIR: path.join(run,"ui-extension"), CMUI_PROVIDER_MODE: "test",
  CMUI_COVERAGE_REVIEWER: "deterministic", CMUI_ALLOW_BILLABLE: "false",
  CMUI_AUTO_VERIFY_NEW_USERS: "false", CMUI_ALLOWED_ORIGINS: "http://127.0.0.1:5373",
  WEB_ORIGIN: "http://127.0.0.1:5373", UI_TASK_AGENT_URL: "http://127.0.0.1:8201",
  NODE_ENV: "test", AUTH_TEST_USER_ID: "codex-audit-verified",
  AGENT_DATABASE_PATH: path.join(run,"agent.sqlite3"), AGENT_PROVIDER_MODE: "deterministic",
  AGENT_PORT: "8201", AGENT_HOST: "127.0.0.1",
};
// Playwright merges webServer.env with its own environment. Strip inheritance
// at the actual service process boundary, not just in the config object.
function isolatedCommand(executable:string,args:string[]) {
  return [python,"-B",path.join(root,"scripts/prepare_codex_audit_e2e.py"),"--serve",executable,...args]
    .map(value=>`"${value}"`).join(" ");
}
if (!inheritedRun) {
  execFileSync(python,["-B",path.join(root,"scripts/prepare_codex_audit_e2e.py"),run],{cwd:root,env:safeEnv,stdio:"inherit"});
  execFileSync(node,["--input-type=module","-e",
    "import {build} from 'vite'; await build({root:process.env.AUDIT_WEB_ROOT,envDir:false,build:{outDir:process.env.AUDIT_WEB_OUT,emptyOutDir:true}});"],
    {cwd:root,stdio:"inherit",env:{...safeEnv,NODE_ENV:"production",AUDIT_WEB_ROOT:path.join(root,"apps/web"),AUDIT_WEB_OUT:path.join(run,"web-dist"),
      VITE_AUTH_TEST_TOKEN:"test-session-token",VITE_CLERK_PUBLISHABLE_KEY:"",VITE_UI_API_BASE:"http://127.0.0.1:8200/ui-extension/api/ui/v1",
      VITE_RAG_API_URL:"http://127.0.0.1:8200",VITE_AGENT_API_URL:"http://127.0.0.1:8201",VITE_V3_ENABLED:"true"}});
}

export default defineConfig({
  testDir:"./tests/e2e",testMatch:"codex-audit.spec.ts",workers:1,fullyParallel:false,retries:0,
  timeout:60_000,expect:{timeout:15_000},outputDir:path.join(run,"browser-results"),
  reporter:[["list"],["json",{outputFile:path.join(run,"playwright-report.json")}]],
  use:{baseURL:"http://127.0.0.1:5373",browserName:"chromium",viewport:{width:1440,height:1000},
    launchOptions:{executablePath:"C:/Program Files/Google/Chrome/Application/chrome.exe"},
    serviceWorkers:"block",trace:"retain-on-failure",screenshot:"only-on-failure"},
  webServer:[
    {command:isolatedCommand(python,["-B","-m","uvicorn","scripts.prepare_codex_audit_e2e:create_test_app","--factory","--host","127.0.0.1","--port","8200"]),
      cwd:root,env:safeEnv,url:"http://127.0.0.1:8200/health",reuseExistingServer:false,timeout:90_000,stdout:"pipe",stderr:"pipe"},
    {command:isolatedCommand(node,[path.join(root,"services/agent-api/dist/src/server.js")]),cwd:root,env:safeEnv,
      url:"http://127.0.0.1:8201/health",reuseExistingServer:false,timeout:60_000,stdout:"pipe",stderr:"pipe"},
    {command:isolatedCommand(node,[path.join(root,"scripts/serve_web_dist.mjs"),path.join(run,"web-dist"),"5373"]),
      cwd:root,env:safeEnv,url:"http://127.0.0.1:5373/app",reuseExistingServer:false,timeout:60_000,stdout:"pipe",stderr:"pipe"},
  ],
});
