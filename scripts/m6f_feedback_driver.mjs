// M6F second-admin rejection-feedback driver. Fresh independent session.
// Shows a minimal feedback form (no tokens ever read or printed).
import { chromium } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const OUT = path.join(process.cwd(), "work", `m6f-second-admin-feedback-${Date.now()}.json`);
const browser = await chromium.launch({
  headless: false,
  executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe",
});
const context = await browser.newContext();
const page = await context.newPage();
await page.goto("https://qqttai.com/", { waitUntil: "domcontentloaded" });
console.log("BROWSER_OPENED — second admin: please sign in with YOUR OWN Clerk account.");

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

let ok = false;
for (let i = 0; i < 720; i++) {
  const p = await probe();
  console.log(`AUTH_POLL ${i + 1}/720 status=${p.status}`);
  if (p.status === 200) { ok = true; break; }
  await page.waitForTimeout(5000);
}
if (!ok) { console.log("LOGIN_TIMEOUT"); await browser.close(); process.exit(2); }
console.log("SECOND_ADMIN_READY");

await page.setContent(`<!doctype html><html><head><meta charset="utf-8"><title>M6F rejection reasons</title></head>
<body style="font-family:sans-serif;max-width:760px;margin:24px auto">
<h2>CourseMate 官方知识发布 — 拒绝原因（第二管理员）</h2>
<p>请分别说明两门课程的拒绝原因。此表单不采集任何 token/cookie。</p>
<form id="f">
<h3>CS3481（tree official-tree-15fd7681…）</h3>
<label>分类：</label><select id="cs_cat" required>
<option value="">（必选）</option><option>content</option><option>evidence</option>
<option>structure</option><option>prerequisite</option><option>teaching_spec</option>
<option>ui</option><option>procedural</option><option>accidental</option><option>other</option></select><br>
<textarea id="cs_text" rows="4" cols="80" required minlength="3" placeholder="CS3481 拒绝原因（必填，自由文本）"></textarea>
<h3>GE2324（tree official-tree-168ad777…）</h3>
<label>分类：</label><select id="ge_cat" required>
<option value="">（必选）</option><option>content</option><option>evidence</option>
<option>structure</option><option>prerequisite</option><option>teaching_spec</option>
<option>ui</option><option>procedural</option><option>accidental</option><option>other</option></select><br>
<textarea id="ge_text" rows="4" cols="80" required minlength="3" placeholder="GE2324 拒绝原因（必填，自由文本）"></textarea>
<br><br><button type="submit">提交反馈</button>
</form>
<script>
document.getElementById('f').addEventListener('submit', function(e){
  e.preventDefault();
  window.__m6fFeedback = {
    cs: { category: document.getElementById('cs_cat').value, text: document.getElementById('cs_text').value },
    ge: { category: document.getElementById('ge_cat').value, text: document.getElementById('ge_text').value },
  };
  document.body.innerHTML = '<h2>已记录反馈。可以关闭此窗口。</h2>';
});
</script></body></html>`);
console.log("FORM_SHOWN");

for (let i = 0; i < 360; i++) {
  const feedback = await page.evaluate(() => window.__m6fFeedback ?? null);
  if (feedback) {
    fs.writeFileSync(OUT, JSON.stringify(feedback, null, 2));
    console.log("FEEDBACK_SAVED", OUT);
    console.log("CS_CATEGORY", feedback.cs.category || "(none)");
    console.log("CS_TEXT", (feedback.cs.text || "(none)").slice(0, 200));
    console.log("GE_CATEGORY", feedback.ge.category || "(none)");
    console.log("GE_TEXT", (feedback.ge.text || "(none)").slice(0, 200));
    await browser.close();
    process.exit(0);
  }
  await page.waitForTimeout(10000);
}
console.log("FEEDBACK_TIMEOUT");
await browser.close();
process.exit(3);
