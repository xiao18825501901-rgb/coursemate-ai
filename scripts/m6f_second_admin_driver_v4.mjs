// M6F second-admin review driver v4 (round 4). Fixes the v3 dead-end: v3's
// decide() disabled ALL four buttons after the first decision, so after
// approving CS3481 the GE2324 buttons greyed out and the driver waited forever.
// v4 disables only the decided course's buttons, adds one-click "approve both /
// reject both" buttons, shows progress, and re-applies state if the overlay is
// re-injected. Same-window full-screen overlay (window.Clerk stays alive, all
// API calls run in this tab with the reviewer's own session). No deadlines.
import { chromium } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const WORK = path.join(process.cwd(), "work");
const ID_FILE = path.join(WORK, "m6f-second-admin-id.txt");
const PROMOTION_DONE = path.join(WORK, "m6f-promotion-done.txt");
const CS_REQUEST = process.env.M6F_CS_REQUEST;
const GE_REQUEST = process.env.M6F_GE_REQUEST;
const OUT = path.join(WORK, `m6f-second-admin-v4-${Date.now()}.json`);

const EXPECTED_SNAPSHOT_HASH = {
  CS3481: "5c827ebd323ffcdfd01db36810d1a4ef5ac07b7d1f0931576ae3aa9ef2bd1070",
  GE2324: "7d1a1ec27b3730e4ad9f5f835a1381103641d048ba53f1c78028f1f4770fe82b",
};
const TREE = {
  CS3481: "official-tree-15fd76815c754d148064e5e8872ad35c",
  GE2324: "official-tree-168ad777b4a549debd6614d75c77a09d",
};

const results = { decisions: {}, review: {}, snapshots: {} };

if (!CS_REQUEST || !GE_REQUEST) {
  console.log("MISSING_REQUEST_ENV");
  process.exit(9);
}

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
    div.style.cssText = "position:fixed;top:0;left:0;right:0;z-index:2147483000;background:#1d4ed8;color:#fff;padding:10px 12px;font:bold 15px sans-serif;text-align:center";
    document.body.appendChild(div);
  });
} catch {}
console.log("BROWSER_OPENED — second admin: please sign in with YOUR OWN Clerk account in this window.");

async function probe() {
  try {
    return await page.evaluate(async () => {
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
  } catch { return { status: -1 }; }
}

// ---- Phase A: sign-in (60 min) ----
let signedIn = false;
for (let i = 0; i < 720; i++) {
  const p = await probe();
  console.log(`AUTH_POLL ${i + 1}/720 status=${p.status}`);
  if (p.status === 200 || p.status === 403) { signedIn = true; break; }
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

// ---- verify admin access ----
const adminProbe = await probe();
console.log("SECOND_ADMIN_ACCESS", adminProbe.status);
if (adminProbe.status !== 200) { console.log("SECOND_ADMIN_NOT_ADMIN"); await browser.close(); process.exit(5); }

// ---- fetch the FROZEN snapshots ----
async function fetchSnapshot(requestId) {
  return await page.evaluate(async ({ requestId }) => {
    let token = "";
    try { token = (await window.Clerk?.session?.getToken?.()) ?? ""; } catch { token = ""; }
    const headers = {};
    if (token) headers.Authorization = "Bearer " + token;
    const r = await fetch(`https://rag.qqttai.com/api/admin/knowledge-publication-requests/${requestId}/snapshot`, {
      credentials: "omit", headers,
    });
    return { status: r.status, body: await r.text() };
  }, { requestId });
}

const csSnap = await fetchSnapshot(CS_REQUEST);
console.log("CS3481_SNAPSHOT_HTTP", csSnap.status);
const csSnapBody = JSON.parse(csSnap.body || "{}");
const csHash = csSnapBody.contentHash ?? csSnapBody.content_hash ?? "";
console.log("CS3481_SNAPSHOT_HASH", csHash);
console.log("CS3481_SNAPSHOT_HASH_MATCH", csHash === EXPECTED_SNAPSHOT_HASH.CS3481);

const geSnap = await fetchSnapshot(GE_REQUEST);
console.log("GE2324_SNAPSHOT_HTTP", geSnap.status);
const geSnapBody = JSON.parse(geSnap.body || "{}");
const geHash = geSnapBody.contentHash ?? geSnapBody.content_hash ?? "";
console.log("GE2324_SNAPSHOT_HASH", geHash);
console.log("GE2324_SNAPSHOT_HASH_MATCH", geHash === EXPECTED_SNAPSHOT_HASH.GE2324);

results.snapshots = {
  cs3481: { http: csSnap.status, hash: csHash, match: csHash === EXPECTED_SNAPSHOT_HASH.CS3481 },
  ge2324: { http: geSnap.status, hash: geHash, match: geHash === EXPECTED_SNAPSHOT_HASH.GE2324 },
};

if (csSnap.status !== 200 || geSnap.status !== 200) {
  console.log("SNAPSHOT_FETCH_FAILED");
  await browser.close();
  process.exit(6);
}
if (csHash !== EXPECTED_SNAPSHOT_HASH.CS3481 || geHash !== EXPECTED_SNAPSHOT_HASH.GE2324) {
  console.log("FATAL_HASH_MISMATCH — content drifted after HUMAN_GATE_1; NOT offering review.");
  await browser.close();
  process.exit(7);
}

// ---- overlay review UI (no <script>: events wired via evaluate) ----
function renderResources(resources) {
  const items = (resources ?? []);
  if (items.length === 0) return "<p><i>（快照未包含资源列表）</i></p>";
  return "<ul style='font-size:14px'>" + items.map((r) => {
    const kind = String(r?.kind ?? "?");
    const title = r?.displayName ?? r?.title ?? r?.name ?? r?.id ?? "";
    const version = r?.version ? ` v${r.version}` : "";
    const scope = r?.sourceScope ? ` [${r.sourceScope}]` : "";
    const badge = `<b>[${kind}]</b>`;
    const head = title ? `${badge} ${title}${version}${scope}` : `${badge}${version}${scope}`;
    const json = JSON.stringify(r, null, 2).replace(/</g, "&lt;");
    return `<li>${head}<details><summary>原始 JSON</summary><pre style="font-size:11px;max-height:180px;overflow:auto">${json}</pre></details></li>`;
  }).join("") + "</ul>";
}

const overlayHtml = `
<div style="background:#1d4ed8;color:#fff;padding:12px 16px;font:bold 17px sans-serif">
  CourseMate 官方知识发布 — 第二管理员独立复核（SECOND ADMIN 审核窗口，无时限）
</div>
<div style="padding:20px 24px">
<p>请在本页自行复核以下即将发布的全部内容，<b>没有任何时间限制</b>。本页不采集任何 token/cookie。</p>
<p>发布效果：批准后，该精确内容向学生正式发布；旧版本保留为历史。<br>
人工内容审核状态：HUMAN_GATE_1=PASS（用户已完成内容复核）。</p>
<p style="color:#b91c1c;font-weight:bold">操作：先勾选确认框 → 按钮变亮 → 点击“两门课程全部批准”，或分别点击各门课程的按钮。按钮为灰色时请先勾选确认框。</p>
<section style="border:2px solid #b91c1c;padding:8px 14px;margin:12px 0;background:#fff">
<h3 style="margin:6px 0">CS3481 — tree ${TREE.CS3481}</h3>
<p>冻结快照哈希：<code>${csHash}</code><br>与 HUMAN_GATE_1 冻结值一致：<b>${csHash === EXPECTED_SNAPSHOT_HASH.CS3481 ? "YES" : "NO"}</b></p>
${renderResources(csSnapBody.resources)}
</section>
<section style="border:2px solid #b91c1c;padding:8px 14px;margin:12px 0;background:#fff">
<h3 style="margin:6px 0">GE2324 — tree ${TREE.GE2324}</h3>
<p>冻结快照哈希：<code>${geHash}</code><br>与 HUMAN_GATE_1 冻结值一致：<b>${geHash === EXPECTED_SNAPSHOT_HASH.GE2324 ? "YES" : "NO"}</b></p>
${renderResources(geSnapBody.resources)}
</section>
<p style="background:#fef3c7;padding:10px;border:1px solid #f59e0b">
<label><input type="checkbox" id="m6fAck" style="width:18px;height:18px;vertical-align:middle">
<b>我（第二管理员本人）已亲自复核以上 CS3481 与 GE2324 的全部发布内容。</b></label>
</p>
<div style="margin:16px 0">
<button id="m6fAllApprove" disabled style="background:#15803d;color:#fff;font-size:17px;font-weight:bold;padding:12px 20px;margin:4px">两门课程全部批准</button>
<button id="m6fAllReject" disabled style="background:#991b1b;color:#fff;font-size:17px;font-weight:bold;padding:12px 20px;margin:4px">两门课程全部拒绝</button>
</div>
<div style="margin:12px 0">
<button id="m6fCsApprove" disabled style="background:#16a34a;color:#fff;font-size:15px;padding:9px 14px;margin:4px">CS3481 批准</button>
<button id="m6fCsReject" disabled style="background:#dc2626;color:#fff;font-size:15px;padding:9px 14px;margin:4px">CS3481 拒绝</button>
<button id="m6fGeApprove" disabled style="background:#16a34a;color:#fff;font-size:15px;padding:9px 14px;margin:4px 4px 4px 24px">GE2324 批准</button>
<button id="m6fGeReject" disabled style="background:#dc2626;color:#fff;font-size:15px;padding:9px 14px;margin:4px">GE2324 拒绝</button>
</div>
<p id="m6fProgress" style="font-weight:bold">已决定：CS3481 = （未决定）；GE2324 = （未决定）</p>
<pre id="m6fLog" style="background:#f3f4f6;padding:10px;min-height:40px;white-space:pre-wrap"></pre>
</div>`;

async function injectOverlay() {
  const fresh = await page.evaluate(({ overlayHtml }) => {
    const existing = document.getElementById("__m6fOverlay");
    if (existing) { existing.scrollIntoView(); return false; }
    const ov = document.createElement("div");
    ov.id = "__m6fOverlay";
    ov.style.cssText = "position:fixed;inset:0;background:#f9fafb;z-index:2147482999;overflow:auto;font-family:sans-serif;color:#111";
    ov.innerHTML = overlayHtml;
    document.body.appendChild(ov);
    window.__m6fWired = false; // listeners must be attached to the new DOM
    ov.scrollIntoView();
    return true;
  }, { overlayHtml });
  return fresh;
}

async function wireEvents() {
  await page.evaluate(() => {
    const ack = document.getElementById("m6fAck");
    if (!ack) return; // overlay not present yet
    if (ack.dataset.wired === "1") return;
    ack.dataset.wired = "1";
    const perCourse = { m6fCsApprove: "cs", m6fCsReject: "cs", m6fGeApprove: "ge", m6fGeReject: "ge" };
    const bulk = ["m6fAllApprove", "m6fAllReject"];
    const allIds = [...Object.keys(perCourse), ...bulk];
    if (!window.__m6fDecisions) window.__m6fDecisions = {};
    const decided = window.__m6fDecisions;

    function sync() {
      const bothDone = !!(decided.cs && decided.ge);
      for (const id of allIds) {
        const el = document.getElementById(id);
        if (!el) continue;
        const course = perCourse[id] ?? null;
        el.disabled = !ack.checked || bothDone || (course ? !!decided[course] : false);
      }
      ack.disabled = bothDone;
      const label = (v) => v ?? "（未决定）";
      const progress = document.getElementById("m6fProgress");
      if (progress) {
        progress.textContent = `已决定：CS3481 = ${label(decided.cs)}；GE2324 = ${label(decided.ge)}`;
      }
    }

    function decide(course, verdict) {
      if (decided[course]) return;
      decided[course] = verdict;
      const log = document.getElementById("m6fLog");
      if (log) log.textContent += "\n" + course + " -> " + verdict + "（已记录，等待系统执行）";
      if (decided.cs && decided.ge) window.__m6fDone = true;
      sync();
    }

    ack.addEventListener("change", sync);
    for (const [id, course] of Object.entries(perCourse)) {
      const el = document.getElementById(id);
      if (!el) continue;
      const verdict = id.toLowerCase().includes("approve") ? "approve" : "reject";
      el.addEventListener("click", function () { decide(course, verdict); });
    }
    document.getElementById("m6fAllApprove")?.addEventListener("click", function () {
      decide("cs", "approve"); decide("ge", "approve");
    });
    document.getElementById("m6fAllReject")?.addEventListener("click", function () {
      decide("cs", "reject"); decide("ge", "reject");
    });
    sync();
  });
}

const freshInjected = await injectOverlay();
if (freshInjected) console.log("OVERLAY_SHOWN — same window, no deadline; reviewer works at their own pace.");
await wireEvents();
console.log("EVENTS_WIRED");

// ---- wait for BOTH decisions (unlimited), self-healing the overlay ----
let decisions = null;
let reInjected = 0;
for (;;) {
  try {
    const state = await page.evaluate(() => ({
      done: window.__m6fDone === true,
      overlay: !!document.getElementById("__m6fOverlay"),
      decisions: window.__m6fDecisions ?? null,
    }));
    if (state.done && state.decisions && state.decisions.cs && state.decisions.ge) {
      decisions = state.decisions;
      break;
    }
    if (!state.overlay) {
      await injectOverlay();
      await wireEvents();
      reInjected += 1;
      console.log("OVERLAY_REINJECTED", reInjected);
    }
  } catch (e) {
    // transient navigation/context errors: keep waiting
  }
  await page.waitForTimeout(2000);
}
console.log("DECISIONS", JSON.stringify(decisions));

// ---- execute the official review endpoint with the second admin session ----
async function postReview(requestId, verdict) {
  return await page.evaluate(async ({ requestId, verdict }) => {
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
}

let fatal = false;
const csRes = await postReview(CS_REQUEST, decisions.cs);
console.log("REVIEW CS3481 verdict=" + decisions.cs + " http=" + csRes.status);
results.decisions.CS3481 = decisions.cs;
results.review.CS3481 = { status: csRes.status, body: JSON.parse(csRes.body || "{}") };
if (csRes.status === 409) {
  console.log("FATAL_INDEPENDENT_REVIEW_VIOLATION on CS3481 — aborting before GE2324 review.");
  fatal = true;
} else {
  const geRes = await postReview(GE_REQUEST, decisions.ge);
  console.log("REVIEW GE2324 verdict=" + decisions.ge + " http=" + geRes.status);
  results.decisions.GE2324 = decisions.ge;
  results.review.GE2324 = { status: geRes.status, body: JSON.parse(geRes.body || "{}") };
  if (geRes.status === 409) {
    console.log("FATAL_INDEPENDENT_REVIEW_VIOLATION on GE2324.");
    fatal = true;
  }
}

fs.writeFileSync(OUT, JSON.stringify(results, null, 2));
console.log("RESULTS_SAVED", OUT);
console.log("PHASE_COMPLETE=second-admin-review-v4");
await browser.close();
process.exit(fatal ? 10 : 0);
