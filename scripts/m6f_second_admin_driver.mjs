// M6F second-admin driver. A FRESH browser instance for the second real admin.
// Phase A: wait for sign-in, capture Clerk user id (masked in logs).
// Phase B: after promotion signal file appears, verify admin access, present
//          both pending requests via real confirm() dialogs (OK=approve,
//          Cancel=reject), execute the official review endpoint with the
//          second admin's own session, and verify transitions.
import { chromium } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const WORK = path.join(process.cwd(), "work");
const ID_FILE = path.join(WORK, "m6f-second-admin-id.txt");
const PROMOTION_DONE = path.join(WORK, "m6f-promotion-done.txt");
const CS_REQUEST = process.env.M6F_CS_REQUEST;
const GE_REQUEST = process.env.M6F_GE_REQUEST;
const OUT = path.join(WORK, `m6f-second-admin-${Date.now()}.json`);
const results = { decisions: {}, review: {} };

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
    div.textContent = "SECOND ADMIN 审核窗口 — 请使用【第二位真实管理员】账号登录（不要用第一管理员账号）";
    div.style.cssText = "position:fixed;top:0;left:0;right:0;z-index:99999;background:#1d4ed8;color:#fff;padding:10px 12px;font:bold 15px sans-serif;text-align:center";
    document.body.appendChild(div);
  });
} catch {}
console.log("BROWSER_OPENED — second admin: please sign in with YOUR OWN Clerk account in this window.");

async function probe() {
  return page.evaluate(async () => {
    try {
      let token = "";
      try { token = (await window.Clerk?.session?.getToken?.()) ?? ""; } catch { token = ""; }
      const headers = {};
      if (token) headers.Authorization = "Bearer " + token;
      const r = await fetch("https://rag.qqttai.com/api/admin/knowledge-publication-requests", {
        credentials: "omit", headers,
      });
      return { status: r.status };
    } catch { return { status: -1 }; }
  });
}

// ---- Phase A: sign-in ----
let signedIn = false;
for (let i = 0; i < 180; i++) {
  const p = await probe();
  console.log(`AUTH_POLL ${i + 1}/180 status=${p.status}`);
  if (p.status === 200 || p.status === 403) { signedIn = true; break; } // 403 = signed in but not yet admin
  await page.waitForTimeout(5000);
}
if (!signedIn) { console.log("SECOND_ADMIN_LOGIN_TIMEOUT"); await browser.close(); process.exit(2); }
const userId = await page.evaluate(() => window.Clerk?.user?.id ?? "");
if (!userId) { console.log("SECOND_ADMIN_ID_MISSING"); await browser.close(); process.exit(3); }
fs.writeFileSync(ID_FILE, userId, "utf8");
console.log("SECOND_ADMIN_SIGNED_IN user=" + userId.slice(0, 6) + "...");
console.log("SIGNAL=SECOND_ADMIN_SIGNED_IN");

// ---- wait for the server-side promotion to finish ----
for (let i = 0; i < 180; i++) {
  if (fs.existsSync(PROMOTION_DONE)) break;
  await page.waitForTimeout(3000);
}
if (!fs.existsSync(PROMOTION_DONE)) { console.log("PROMOTION_TIMEOUT"); await browser.close(); process.exit(4); }
console.log("PROMOTION_CONFIRMED");

// ---- Phase B: verify admin access ----
const adminProbe = await probe();
console.log("SECOND_ADMIN_ACCESS", adminProbe.status);
if (adminProbe.status !== 200) { console.log("SECOND_ADMIN_NOT_ADMIN"); await browser.close(); process.exit(5); }

async function review(requestId, courseLabel, treeId, hash) {
  const decision = await page.evaluate(async ({ courseLabel, treeId, hash }) => {
    return window.confirm(
      `CourseMate official knowledge publication — ${courseLabel}\n\n` +
      `Tree (V3): ${treeId}\nContent hash: ${hash}\n\n` +
      `Human review status: HUMAN_GATE_1=PASS (user content review approved)\n` +
      `Publication effect: publishes this exact tree to students; old trees stay as history.\n\n` +
      `Click OK to APPROVE, Cancel to REJECT.`
    );
  }, { courseLabel, treeId, hash });
  const verdict = decision ? "approve" : "reject";
  const res = await page.evaluate(async ({ requestId, verdict }) => {
    let token = "";
    try { token = (await window.Clerk?.session?.getToken?.()) ?? ""; } catch { token = ""; }
    const headers = { "Content-Type": "application/json" };
    if (token) headers.Authorization = "Bearer " + token;
    const r = await fetch(`https://rag.qqttai.com/api/admin/knowledge-publication-requests/${requestId}/review`, {
      method: "POST", credentials: "omit", headers,
      body: JSON.stringify({ decision: verdict, reviewNote: "Second administrator independent review (M6F)." }),
    });
    return { status: r.status, body: await r.text() };
  }, { requestId, verdict });
  console.log(`REVIEW ${courseLabel} verdict=${verdict} http=${res.status}`);
  results.decisions[courseLabel] = verdict;
  results.review[courseLabel] = { status: res.status, body: JSON.parse(res.body || "{}") };
  return { verdict, res };
}

const csReview = await review(CS_REQUEST, "CS3481", "official-tree-15fd76815c754d148064e5e8872ad35c",
  "5a4dda623d108ca1071d15710ad25b433e995381c4433492dc3b9c8853f7cb13");
const geReview = await review(GE_REQUEST, "GE2324", "official-tree-168ad777b4a549debd6614d75c77a09d",
  "1719457fb95b5abe5619e05eb2da9a96e48fb80846b4eefdf357ef8b1bfd0c62");

fs.writeFileSync(OUT, JSON.stringify(results, null, 2));
console.log("RESULTS_SAVED", OUT);
console.log("PHASE_COMPLETE=second-admin-review");
await browser.close();
process.exit(0);
