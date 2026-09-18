// M6F interactive publication driver (runs in a visible Chrome window).
// The user signs in with their real Clerk account themselves; the session
// never leaves the browser. Tokens are never printed, only API responses.
import { chromium } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const CS_TREE = "official-tree-15fd76815c754d148064e5e8872ad35c";
const GE_TREE = "official-tree-168ad777b4a549debd6614d75c77a09d";
const EXPECTED_HASH = {
  cs3481: "5c827ebd323ffcdfd01db36810d1a4ef5ac07b7d1f0931576ae3aa9ef2bd1070",
  ge2324: "7d1a1ec27b3730e4ad9f5f835a1381103641d048ba53f1c78028f1f4770fe82b",
};
const OUT = path.join(process.cwd(), "work", `m6f-publication-${Date.now()}.json`);
const results = { phase: "interactive-auth", steps: [] };

const browser = await chromium.launch({
  headless: false,
  executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe",
});
const context = await browser.newContext();
const page = await context.newPage();
await page.goto("https://qqttai.com/", { waitUntil: "domcontentloaded" });
try {
  await page.evaluate(() => {
    const div = document.createElement("div");
    div.textContent = "FIRST ADMIN 提交窗口 — 请使用【第一管理员】账号登录（不要用第二管理员账号）";
    div.style.cssText = "position:fixed;top:0;left:0;right:0;z-index:99999;background:#b91c1c;color:#fff;padding:10px 12px;font:bold 15px sans-serif;text-align:center";
    document.body.appendChild(div);
  });
} catch {}
console.log("BROWSER_OPENED qqttai.com — please sign in with your first admin Clerk account in the opened window.");

// 1. wait for admin session (poll the real admin endpoint via the official Clerk token)
let adminVerified = false;
for (let i = 0; i < 720; i++) {
  let probe;
  try {
    probe = await page.evaluate(async () => {
      try {
        let token = "";
        try {
          token = (await window.Clerk?.session?.getToken?.()) ?? "";
        } catch {
          token = "";
        }
        const headers = {};
        if (token) headers.Authorization = "Bearer " + token;
        const r = await fetch("https://rag.qqttai.com/api/admin/knowledge-publication-drafts", {
          credentials: "omit",
          headers,
        });
        return { status: r.status, ok: r.ok };
      } catch (e) {
        return { status: -1, err: String(e).slice(0, 60) };
      }
    });
  } catch {
    probe = { status: -1 };
  }
  console.log(`AUTH_POLL ${i + 1}/720 status=${probe.status}`);
  if (probe.status === 200) {
    adminVerified = true;
    break;
  }
  await page.waitForTimeout(5000);
}
if (!adminVerified) {
  console.log("LOGIN_TIMEOUT — no admin session detected in 60 minutes");
  await browser.close();
  process.exit(2);
}
console.log("FIRST_ADMIN_VERIFIED=YES");
results.phase = "first-admin";

// 2. submit CS3481 publication request
async function call(method, url, body) {
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      return await page.evaluate(
        async ({ method, url, body }) => {
          let token = "";
          try {
            token = (await window.Clerk?.session?.getToken?.()) ?? "";
          } catch {
            token = "";
          }
          const headers = {};
          if (token) headers.Authorization = "Bearer " + token;
          if (body !== undefined) headers["Content-Type"] = "application/json";
          const r = await fetch(url, {
            method,
            credentials: "omit",
            headers,
            body: body !== undefined ? JSON.stringify(body) : undefined,
          });
          return { status: r.status, body: await r.text() };
        },
        { method, url, body },
      );
    } catch {
      await page.waitForTimeout(2000);
    }
  }
  return { status: -1, body: "{}" };
}

const csSubmit = await call("POST", "https://rag.qqttai.com/api/admin/knowledge-publication-requests", {
  treeVersionId: CS_TREE,
});
console.log("CS3481_SUBMIT", csSubmit.status);
results.steps.push({ step: "cs3481_submit", status: csSubmit.status, body: JSON.parse(csSubmit.body || "{}") });
const csRequest = JSON.parse(csSubmit.body || "{}");
results.CS3481_REQUEST_ID = csRequest.id ?? null;

if (csSubmit.status !== 201) {
  console.log("CS3481_SUBMIT_FAILED", csSubmit.body.slice(0, 500));
  await browser.close();
  process.exit(3);
}
console.log("CS3481_REQUEST_ID", csRequest.id, "status", csRequest.status, "snapshotHash", csRequest.snapshotHash);

// 3. frozen snapshot verification for CS3481
const csSnapshot = await call("GET", `https://rag.qqttai.com/api/admin/knowledge-publication-requests/${csRequest.id}/snapshot`);
console.log("CS3481_SNAPSHOT", csSnapshot.status);
const csSnapBody = JSON.parse(csSnapshot.body || "{}");
console.log("CS3481_SNAPSHOT_HASH", csSnapBody.content_hash);
console.log("CS3481_SNAPSHOT_HASH_MATCH", csSnapBody.content_hash === EXPECTED_HASH.cs3481);
console.log("CS3481_SNAPSHOT_KINDS", [...new Set((csSnapBody.resources ?? []).map((r) => r.kind))].join(","));
results.steps.push({ step: "cs3481_snapshot", status: csSnapshot.status, hash: csSnapBody.content_hash, match: csSnapBody.content_hash === EXPECTED_HASH.cs3481 });

// 4. submit GE2324 publication request
const geSubmit = await call("POST", "https://rag.qqttai.com/api/admin/knowledge-publication-requests", {
  treeVersionId: GE_TREE,
});
console.log("GE2324_SUBMIT", geSubmit.status);
const geRequest = JSON.parse(geSubmit.body || "{}");
results.GE2324_REQUEST_ID = geRequest.id ?? null;
if (geSubmit.status !== 201) {
  console.log("GE2324_SUBMIT_FAILED", geSubmit.body.slice(0, 500));
  await browser.close();
  process.exit(4);
}
console.log("GE2324_REQUEST_ID", geRequest.id, "status", geRequest.status, "snapshotHash", geRequest.snapshotHash);

const geSnapshot = await call("GET", `https://rag.qqttai.com/api/admin/knowledge-publication-requests/${geRequest.id}/snapshot`);
console.log("GE2324_SNAPSHOT", geSnapshot.status);
const geSnapBody = JSON.parse(geSnapshot.body || "{}");
console.log("GE2324_SNAPSHOT_HASH", geSnapBody.content_hash);
console.log("GE2324_SNAPSHOT_HASH_MATCH", geSnapBody.content_hash === EXPECTED_HASH.ge2324);
console.log("GE2324_SNAPSHOT_KINDS", [...new Set((geSnapBody.resources ?? []).map((r) => r.kind))].join(","));
results.steps.push({ step: "ge2324_snapshot", status: geSnapshot.status, hash: geSnapBody.content_hash, match: geSnapBody.content_hash === EXPECTED_HASH.ge2324 });

// 5. self-review must be rejected (first admin reviewing own submission)
const selfReview = await call("POST", `https://rag.qqttai.com/api/admin/knowledge-publication-requests/${csRequest.id}/review`, {
  decision: "approve",
  reviewNote: "SELF-REVIEW MUST FAIL CHECK",
});
console.log("SELF_REVIEW", selfReview.status, (JSON.parse(selfReview.body || "{}").error ?? {}).code ?? "");
results.steps.push({ step: "self_review", status: selfReview.status, body: JSON.parse(selfReview.body || "{}") });

fs.writeFileSync(OUT, JSON.stringify(results, null, 2));
console.log("RESULTS_SAVED", OUT);
console.log("PHASE_COMPLETE=first-admin-work");
await browser.close();
process.exit(0);
