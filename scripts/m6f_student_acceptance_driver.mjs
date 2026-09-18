// M6F student/UI acceptance driver (post-publication, read-only).
// A real human signs in with their own Clerk account (student view — the same
// account may be a student of cs3481/ge2324). The driver then:
//   1. resolves which of the known workspaces that account owns,
//   2. GETs the STUDENT knowledge endpoint for each course and asserts the
//      offline-reviewed OFFICIAL tree is now served to students,
//   3. opens the real student UI page /learn/<courseId> and screenshots it.
// Read-only: it never POSTs, so it cannot trigger model generation.
import { chromium } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const WORK = path.join(process.cwd(), "work");
const STAMP = Date.now();
const OUT = path.join(WORK, `m6f-student-acceptance-${STAMP}.json`);
const BASE = "https://rag.qqttai.com";
const APP = "https://qqttai.com";

const CANDIDATE_WORKSPACES = {
  cs3481: [
    "38d4e19d-1459-41ba-beae-adb37af0c6b3",
    "53aa37c1-e994-4689-93a6-bdbb009219ad",
  ],
  ge2324: [
    "5be28ad6-0a76-4883-a893-82e910221b85",
    "308505d4-0bf5-4548-85a9-0f01aae5cebf",
  ],
};
const EXPECTED_MEMBERS = { cs3481: 22, ge2324: 21 };
const PUBLISHED_TREE = {
  cs3481: "official-tree-15fd76815c754d148064e5e8872ad35c",
  ge2324: "official-tree-168ad777b4a549debd6614d75c77a09d",
};

const evidence = { stamp: STAMP, workspaces: {}, student_api: {}, ui: {}, verdict: {} };

const browser = await chromium.launch({
  headless: false,
  executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe",
});
const context = await browser.newContext();
const page = await context.newPage();
await page.goto(`${APP}/`, { waitUntil: "domcontentloaded" });
try {
  await page.evaluate(() => {
    const div = document.createElement("div");
    div.textContent = "STUDENT / USER 学生视角验收窗口 — 请用你自己的真实 Clerk 账号登录（学生视角，只读）";
    div.style.cssText = "position:fixed;top:0;left:0;right:0;z-index:2147483000;background:#065f46;color:#fff;padding:10px 12px;font:bold 15px sans-serif;text-align:center";
    document.body.appendChild(div);
  });
} catch {}
console.log("BROWSER_OPENED — please sign in with your own Clerk account (student view).");

async function apiGet(url) {
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      return await page.evaluate(async ({ url }) => {
        let token = "";
        try { token = (await window.Clerk?.session?.getToken?.()) ?? ""; } catch { token = ""; }
        const headers = {};
        if (token) headers.Authorization = "Bearer " + token;
        const r = await fetch(url, { credentials: "omit", headers });
        return { status: r.status, body: await r.text() };
      }, { url });
    } catch {
      await page.waitForTimeout(1500);
    }
  }
  return { status: -1, body: "{}" };
}

// ---- sign-in ----
let signedIn = false;
for (let i = 0; i < 720; i++) {
  const probe = await apiGet(`${BASE}/api/learning/workspaces/${CANDIDATE_WORKSPACES.cs3481[0]}`);
  console.log(`AUTH_POLL ${i + 1}/720 status=${probe.status}`);
  if (probe.status === 200 || probe.status === 403 || probe.status === 404) { signedIn = true; break; }
  await page.waitForTimeout(5000);
}
if (!signedIn) { console.log("USER_LOGIN_TIMEOUT"); await browser.close(); process.exit(2); }
console.log("USER_SIGNED_IN");

// ---- resolve accessible workspaces ----
for (const courseId of Object.keys(CANDIDATE_WORKSPACES)) {
  for (const workspaceId of CANDIDATE_WORKSPACES[courseId]) {
    const r = await apiGet(`${BASE}/api/learning/workspaces/${workspaceId}`);
    console.log(`WORKSPACE_PROBE ${courseId} ${workspaceId.slice(0, 8)}… status=${r.status}`);
    if (r.status === 200) {
      evidence.workspaces[courseId] = workspaceId;
      break;
    }
  }
}
console.log("WORKSPACES", JSON.stringify(evidence.workspaces));
if (!evidence.workspaces.cs3481 || !evidence.workspaces.ge2324) {
  console.log("NO_ACCESSIBLE_WORKSPACE_FOR_BOTH_COURSES");
  fs.writeFileSync(OUT, JSON.stringify(evidence, null, 2));
  await browser.close();
  process.exit(3);
}

// ---- student knowledge endpoint ----
for (const courseId of Object.keys(evidence.workspaces)) {
  const workspaceId = evidence.workspaces[courseId];
  const r = await apiGet(`${BASE}/api/learning/workspaces/${workspaceId}/knowledge`);
  let body = {};
  try { body = JSON.parse(r.body || "{}"); } catch { body = {}; }
  const official = body.official_tree ?? null;
  const members = Array.isArray(official?.members) ? official.members : [];
  const sources = [...new Set(members.map((m) => m.source))];
  const allPublished = members.length > 0 && sources.length === 1 && sources[0] === "CANONICAL";
  const titles = members.slice(0, 6).map((m) => m.title);
  const summary = {
    http: r.status,
    official_status: official?.status ?? null,
    official_tree_id: official?.id ?? null,
    official_tree_version: official?.version ?? null,
    tree_id_matches: official?.id === PUBLISHED_TREE[courseId],
    member_count: members.length,
    expected_members: EXPECTED_MEMBERS[courseId],
    member_sources: sources,
    all_members_published: allPublished,
    sample_titles: titles,
    registry_size: Array.isArray(body.registry) ? body.registry.length : null,
    expected_tree: PUBLISHED_TREE[courseId],
  };
  evidence.student_api[courseId] = summary;
  console.log(`STUDENT_API ${courseId} http=${summary.http} official_status=${summary.official_status} members=${summary.member_count}/${summary.expected_members} allPublished=${summary.all_members_published}`);
  console.log(`STUDENT_API ${courseId} titles=${JSON.stringify(titles.slice(0, 4))}`);
  evidence.verdict[courseId] = {
    served: summary.http === 200 && summary.official_status === "PUBLISHED",
    tree_id_matches_published_v3: summary.tree_id_matches === true,
    member_count_ok: summary.member_count === summary.expected_members,
    all_published: summary.all_members_published,
  };
  fs.writeFileSync(path.join(WORK, `m6f-student-knowledge-${courseId}-${STAMP}.json`), JSON.stringify(body, null, 2));
}

// ---- real student UI page ----
for (const courseId of Object.keys(evidence.workspaces)) {
  const url = `${APP}/learn/${courseId}`;
  try {
    await page.goto(url, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(6000);
    const shot = path.join(WORK, `m6f-student-ui-${courseId}-${STAMP}.png`);
    await page.screenshot({ path: shot });
    const text = await page.evaluate(() => document.body.innerText.slice(0, 1200));
    evidence.ui[courseId] = { url, screenshot: shot, text_sample: text };
    console.log(`UI_PAGE ${courseId} url=${url} screenshot=${shot}`);
    console.log(`UI_TEXT ${courseId} ${JSON.stringify(text.slice(0, 200))}`);
  } catch (e) {
    evidence.ui[courseId] = { url, error: String(e).slice(0, 160) };
    console.log(`UI_PAGE_ERROR ${courseId} ${String(e).slice(0, 120)}`);
  }
}

const pass = Object.values(evidence.verdict).every(
  (v) => v.served && v.tree_id_matches_published_v3 && v.member_count_ok && v.all_published,
);
evidence.student_acceptance = pass ? "PASS" : "FAIL";
fs.writeFileSync(OUT, JSON.stringify(evidence, null, 2));
console.log("STUDENT_ACCEPTANCE", evidence.student_acceptance);
console.log("RESULTS_SAVED", OUT);
await browser.close();
process.exit(pass ? 0 : 4);
