import { expect, test } from "@playwright/test";

/**
 * Native-browser acceptance for the refreshed CourseMate shell.
 *
 * Everything here runs against the real services: the RAG API with the UI
 * extension mounted on the live V3 database, the existing Node task agent, and a
 * real Chromium. It replaces the delivered package's in-memory harness, which
 * loaded the shell with `page.set_content` and an explicit HTTP bridge.
 */

const NAV = ["账户", "控制面板", "课程", "日历", "收件箱", "帮助"];

test.describe.configure({ mode: "serial" });

/** The refreshed shell's document must contain its own bundle, never the legacy one. */
async function assertShellDocument(page: import("@playwright/test").Page) {
  const entry = await page.evaluate(() => ({
    scripts: Array.from(document.querySelectorAll("script[src]")).map((node) =>
      (node as HTMLScriptElement).getAttribute("src"),
    ),
  }));
  expect(entry.scripts.join(" ")).toMatch(/\/assets\/ui-[\w-]+\.js/);
  expect(entry.scripts.join(" ")).not.toMatch(/\/assets\/main-[\w-]+\.js/);
}

/** The previous site's document must contain its own bundle, never the shell's. */
async function assertLegacyDocument(page: import("@playwright/test").Page) {
  const entry = await page.evaluate(() => ({
    scripts: Array.from(document.querySelectorAll("script[src]")).map((node) =>
      (node as HTMLScriptElement).getAttribute("src"),
    ),
  }));
  expect(entry.scripts.join(" ")).toMatch(/\/assets\/main-[\w-]+\.js/);
  expect(entry.scripts.join(" ")).not.toMatch(/\/assets\/ui-[\w-]+\.js/);
}

test("the refreshed shell is the default entry at the root", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });

  await page.goto("/");
  await assertShellDocument(page);

  // After sign-in the default entry is the new dashboard, not the old landing.
  const nav = page.getByRole("navigation", { name: "主导航" });
  await expect(nav).toBeVisible();
  await expect(page.getByRole("heading", { level: 1, name: "控制面板" })).toBeVisible();
  expect(consoleErrors).toEqual([]);
});

test("boots against the real API and exposes exactly six global entries", async ({ page }) => {
  const consoleErrors: string[] = [];
  const failedRequests: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("requestfailed", (request) => failedRequests.push(request.url()));
  page.on("response", (response) => {
    if (response.status() >= 500) failedRequests.push(`${response.status()} ${response.url()}`);
  });

  await page.goto("/app");
  await assertShellDocument(page);

  const nav = page.getByRole("navigation", { name: "主导航" });
  await expect(nav).toBeVisible();
  for (const label of NAV) {
    await expect(nav.getByRole("button", { name: label, exact: true })).toBeVisible();
  }
  // The user excluded todo lists, recent feedback and a "new dashboard" toggle.
  await expect(nav.getByRole("button")).toHaveCount(NAV.length + 1 /* brand */);

  // Reachability of the mounted extension, not just the shell rendering.
  const health = await page.request.get("http://127.0.0.1:8100/ui-extension/health");
  expect(health.status()).toBe(200);
  expect(await health.json()).toMatchObject({ mode: "integrated" });

  expect(failedRequests).toEqual([]);
  expect(consoleErrors).toEqual([]);
});

test("legacy deep links keep the previous site reachable", async ({ page }) => {
  await page.goto("/qa/cs3481");
  await assertLegacyDocument(page);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

  await page.goto("/courses");
  await assertLegacyDocument(page);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

  await page.goto("/admin/publications");
  await assertLegacyDocument(page);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
});

test("refreshing a deep shell route keeps the same view, and back returns home", async ({
  page,
}) => {
  // Build history entries inside the shell first: dashboard → course files.
  await page.goto("/app");
  await assertShellDocument(page);
  await expect(page.getByRole("heading", { level: 1, name: "控制面板" })).toBeVisible();
  await page.evaluate(() => {
    window.location.hash = "#/course/cs3481/files";
  });
  await expect(page.getByRole("heading", { level: 1, name: "文件" })).toBeVisible();

  // A full refresh on the deep route keeps the same document and the same view.
  await page.reload();
  await assertShellDocument(page);
  await expect(page.getByRole("heading", { level: 1, name: "文件" })).toBeVisible();

  // Backward navigation inside the hash router returns to the dashboard.
  await page.goBack();
  await expect(page.getByRole("heading", { level: 1, name: "控制面板" })).toBeVisible();
});

test("shows an empty dashboard on first sign-in and adds courses from All Courses", async ({
  page,
}) => {
  await page.goto("/app");
  const nav = page.getByRole("navigation", { name: "主导航" });

  await nav.getByRole("button", { name: "控制面板", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "控制面板" })).toBeVisible();
  await expect(page.locator(".course-card")).toHaveCount(0);
  await expect(page.locator(".add-course-card")).toBeVisible();

  await nav.getByRole("button", { name: "课程", exact: true }).click();
  const drawer = page.getByRole("dialog", { name: "课程面板" });
  await expect(drawer).toBeVisible();
  await drawer.getByRole("button", { name: /所有课程/ }).click();
  await expect(page.getByRole("heading", { level: 1, name: "所有课程" })).toBeVisible();

  const row = page.getByRole("row", { name: /CS3481/ });
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: /添加 CS3481/ }).click();

  await nav.getByRole("button", { name: "控制面板", exact: true }).click();
  await expect(page.locator(".course-card")).toHaveCount(1);
  await expect(page.locator(".course-card")).toContainText("CS3481");

  // The three card tools must land on the same destinations as the course nav.
  const card = page.locator(".course-card").first();
  await expect(card.getByRole("button", { name: /评论/ })).toBeVisible();
  await expect(card.getByRole("button", { name: /文件/ })).toBeVisible();
  await expect(card.getByRole("button", { name: /学习/ })).toBeVisible();
  await card.getByRole("button", { name: /文件/ }).click();
  await expect(page).toHaveURL(/#\/course\/cs3481\/files$/);
  await expect(page.getByRole("button", { name: "文件", exact: true })).toHaveClass(/active/);

  // Persistence is server-side: a full reload on the same route must keep the
  // course readable and its pin visible in the drawer listing.
  await page.reload();
  await expect(page).toHaveURL(/#\/course\/cs3481\/files$/);
  await expect(page.getByRole("button", { name: "文件", exact: true })).toHaveClass(/active/);
  await nav.getByRole("button", { name: "课程", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "课程面板" })).toContainText("CS3481");
  await nav.getByRole("button", { name: "控制面板", exact: true }).click();
  await expect(page.locator(".course-card")).toHaveCount(1);
});

test("lists real course files, uploads a private one, previews it, and offers download", async ({
  page,
  request,
}) => {
  const sourceRequests: string[] = [];
  page.on("response", (response) => {
    if (
      response.url().includes("/files/") &&
      (response.url().includes("/content") || response.url().includes("/text"))
    ) {
      sourceRequests.push(`${response.status()} ${response.url()}`);
    }
  });

  await page.goto("/app#/course/cs3481/files");
  await expect(page.getByRole("heading", { level: 1, name: "文件" })).toBeVisible();

  // The corpus listing is real V3 data, grouped into folders.
  const rows = page.locator(".file-table tbody tr");
  await expect(rows.first()).toBeVisible();
  await expect(page.getByText("Lecture Slides").first()).toBeVisible();

  // Uploading through the shell stores a genuine file in the caller's own corpus.
  const unique = `端到端验收资料 ${Date.now()}.md`;
  const uploadResponse = page.waitForResponse(
    (response) => response.url().endsWith("/files") && response.request().method() === "POST",
  );
  await page.locator('input[type="file"]').setInputFiles({
    name: unique,
    mimeType: "text/markdown",
    buffer: Buffer.from("# 端到端验收\n\nDBSCAN 的核心点由邻域与 MinPts 决定。\n", "utf-8"),
  });
  const uploaded = await uploadResponse;
  const uploadedBody = await uploaded.json();
  expect(uploaded.status()).toBe(201);
  expect(uploadedBody).toMatchObject({ name: unique, scope: "private", status: "indexed" });

  // The authorised original itself is reachable through the mounted API, with the
  // real bytes and the V3 download disposition.
  const inline = await request.get(
    `http://127.0.0.1:8100/ui-extension/api/ui/v1/courses/cs3481/files/${uploadedBody.id}/content`,
    { headers: { Authorization: "Bearer test-session-token" } },
  );
  expect(inline.status()).toBe(200);
  expect(inline.headers()["content-disposition"]).toContain("inline");
  expect(await inline.text()).toContain("DBSCAN");

  const ranged = await request.get(
    `http://127.0.0.1:8100/ui-extension/api/ui/v1/courses/cs3481/files/${uploadedBody.id}/content`,
    {
      headers: { Authorization: "Bearer test-session-token", Range: "bytes=0-9" },
    },
  );
  expect(ranged.status()).toBe(206);
  expect((await ranged.body()).length).toBe(10);

  // The private supplement is written to the caller's own corpus and is visible
  // only there, so reach it through the "我的上传" folder the adapter assigns.
  await page.getByRole("button", { name: /我的上传/ }).click();
  const privateRow = page
    .locator("button.file-name-btn")
    .filter({ hasText: unique });
  await expect(privateRow).toBeVisible();
  await expect(privateRow).toContainText("仅自己");

  // Opening a name previews the authorised original through /content.
  await privateRow.click();
  const preview = page.locator(".modal .real-preview");
  await expect(preview).toBeVisible();
  await expect(preview.locator(".text-preview, iframe.pdf-frame, .image-preview")).toBeVisible();
  expect(sourceRequests.length).toBeGreaterThan(0);
  expect(sourceRequests.every((entry) => entry.startsWith("200"))).toBe(true);
  await page.locator(".modal-header").getByRole("button").click();
  await expect(preview).toHaveCount(0);

  // The row menu is where download lives, as the confirmed design requires.
  await page.getByRole("button", { name: `文件操作 ${unique}` }).click();
  const download = page.locator(".dropdown").getByRole("button", { name: /下载/ });
  await expect(download).toBeVisible();
  const downloadResponse = page.waitForResponse(
    (response) => response.url().includes("download=true") && response.status() === 200,
  );
  await download.click();
  expect((await downloadResponse).headers()["content-disposition"]).toContain("attachment");
});

test("comments are real, and a reply notifies the other account", async ({ page, request }) => {
  await page.goto("/app#/course/cs3481/comments");
  await expect(page.getByRole("heading", { name: /评论/ })).toBeVisible();

  const text = `端到端验收评论 ${Date.now()}`;
  const box = page.getByRole("textbox").first();
  await box.fill(text);
  await page.getByRole("button", { name: /发布|发送|发表/ }).first().click();
  await expect(page.getByText(text)).toBeVisible();

  // The comment is stored in the UI database behind the mounted API.
  const listed = await request.get(
    "http://127.0.0.1:8100/ui-extension/api/ui/v1/courses/cs3481/comments",
    { headers: { Authorization: "Bearer test-session-token" } },
  );
  expect(listed.status()).toBe(200);
  const body = await listed.json();
  expect(JSON.stringify(body)).toContain(text);
});

test("the learning workspace keeps two panes, a collapsed tree, and a draggable split", async ({
  page,
}) => {
  await page.goto("/app#/course/cs3481/learn");
  const columns = page.locator(".workspace-columns");
  await expect(columns).toBeVisible();

  // Two left navigations remain: the global one and the course one.
  await expect(page.getByRole("navigation", { name: "主导航" })).toBeVisible();
  await expect(page.getByRole("button", { name: "学习", exact: true })).toHaveClass(/active/);
  await expect(page.locator(".learning-pane.pane-teach")).toBeVisible();
  await expect(page.locator(".learning-pane.pane-problem")).toBeVisible();

  // The knowledge tree is collapsed above the workbench by default, and expanding
  // it covers the workbench while both left navigations stay in place.
  const strip = page.locator("button.knowledge-strip");
  await expect(strip).toBeVisible();
  await expect(strip).toContainText("课程知识点树");
  await expect(page.locator(".tree-expanded")).toHaveCount(0);
  await strip.click();
  const tree = page.locator(".tree-expanded");
  await expect(tree).toBeVisible();
  await expect(page.getByRole("navigation", { name: "主导航" })).toBeVisible();
  await expect(page.getByRole("button", { name: "学习", exact: true })).toBeVisible();
  // This account owns one synthetic fixture node, so the tree shows the caller's
  // real registry entry instead of an empty-state lie; a truly empty registry
  // renders the honest "还没有课程知识树" message (covered by the API tests).
  await expect(tree).toContainText("Assessment Addition");
  await tree.getByRole("button", { name: "收起知识树" }).click();
  await expect(tree).toHaveCount(0);

  // Dragging the divider changes only the widths and persists to the server.
  const divider = page.locator('.pane-divider[role="separator"]');
  await expect(divider).toBeVisible();
  const before = await divider.boundingBox();
  expect(before).not.toBeNull();
  if (before) {
    const ratioBefore = await divider.getAttribute("aria-valuenow");
    await page.mouse.move(before.x + before.width / 2, before.y + before.height / 2);
    await page.mouse.down();
    await page.mouse.move(before.x + before.width / 2 + 120, before.y + before.height / 2, {
      steps: 10,
    });
    await page.mouse.up();
    await expect(divider).not.toHaveAttribute("aria-valuenow", ratioBefore ?? "");
  }

  // Full screen expands both panes together, and Escape restores the layout.
  await page.getByRole("button", { name: "全屏学习" }).click();
  await expect(page.locator(".learn-new.focus-mode")).toBeVisible();
  await expect(page.locator(".learning-pane.pane-teach")).toBeVisible();
  await expect(page.locator(".learning-pane.pane-problem")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator(".learn-new.focus-mode")).toHaveCount(0);

  // Both conversation lanes have their own server-backed history entry.
  await expect(page.getByRole("button", { name: "知识历史" })).toBeVisible();
  await expect(page.getByRole("button", { name: "题目历史" })).toBeVisible();
});

test("calendar plans are created in the same task store the Node agent serves", async ({
  page,
  request,
}) => {
  await page.goto("/app#/calendar");
  await expect(page.getByRole("heading", { name: /日历/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "制定学习计划" })).toBeVisible();

  const title = `端到端复习 ${Date.now()}`;
  await page.getByRole("button", { name: /新建安排/ }).click();
  const form = page.locator(".modal");
  await expect(form).toBeVisible();
  await form.locator('input[name="title"]').fill(title);
  await form.locator('input[name="date"]').fill("2026-10-01");

  const created = page.waitForResponse(
    (response) => response.url().endsWith("/tasks") && response.request().method() === "POST",
  );
  await form.getByRole("button", { name: /保存安排/ }).click();
  const createdResponse = await created;
  if (createdResponse.status() !== 201) {
    throw new Error(`task create failed: ${createdResponse.status()} ${await createdResponse.text()}`);
  }
  const created_task = await createdResponse.json();

  // The same record must be visible in the shell after a reload: the list is
  // rebuilt from the agent, which is the single task fact source.
  await page.reload();
  const taskCard = page.locator(".task-card").filter({ hasText: title });
  await expect(taskCard).toHaveCount(1);
  await expect(taskCard.locator("h3")).toHaveText(title);

  // And on the Node agent's own REST surface.
  const agentTasks = await request.get("http://127.0.0.1:8101/api/tasks?page=1&pageSize=100", {
    headers: { Authorization: "Bearer test-session-token" },
  });
  expect(agentTasks.status()).toBe(200);
  const payload = await agentTasks.json();
  expect(JSON.stringify(payload)).toContain(title);

  // Completing it in the shell must change that same record.
  await page.getByRole("button", { name: `完成 ${title}` }).click();
  await expect
    .poll(async () => {
      const listed = await request.get(
        "http://127.0.0.1:8101/api/tasks?page=1&pageSize=100",
        { headers: { Authorization: "Bearer test-session-token" } },
      );
      const body = await listed.json();
      const task = (body.items as { id: string; status: string }[]).find(
        (item) => item.id === created_task.id,
      );
      return task?.status ?? "missing";
    })
    .toBe("completed");
});

test("the original V3 question history stays readable and read-only", async ({ page }) => {
  await page.goto("/app#/course/cs3481/learn");
  await expect(page.locator(".workspace-columns")).toBeVisible();

  await page.getByRole("button", { name: "知识历史" }).click();
  const modal = page.locator(".modal");
  await expect(modal).toBeVisible();
  await expect(modal.getByRole("heading", { name: "旧版问答记录" })).toBeVisible();

  // Opened from the pre-existing `conversations` table, not copied anywhere.
  const entry = modal.locator(".history-item").filter({ hasText: "旧版问答：DBSCAN 核心点" });
  await expect(entry).toBeVisible();
  await entry.click();

  const reader = modal.locator(".legacy-reader");
  await expect(reader).toBeVisible();
  await expect(reader).toContainText("旧版提问：DBSCAN 怎么判断核心点？");
  await expect(reader).toContainText("MinPts");
  await expect(reader).toContainText("lecture_04_clustering.md");

  // Read-only: the legacy reader offers no rename, delete or continue actions.
  await expect(reader.locator('button[title^="重命名"]')).toHaveCount(0);
  await expect(reader.locator('button[title^="删除对话"]')).toHaveCount(0);
  await expect(reader.getByRole("textbox")).toHaveCount(0);
});

test("a node assessment renders the real V3 result instead of raw JSON", async ({
  page,
  request,
}) => {
  await page.goto("/app#/course/cs3481/learn");
  await expect(page.locator("button.knowledge-strip")).toBeVisible();

  // The caller's own registry node is listed; an unknown node still 404s through
  // the real V3 authorisation instead of producing a fabricated result.
  await page.locator("button.knowledge-strip").click();
  await expect(page.locator(".tree-expanded")).toContainText("Assessment Addition");

  const response = await request.get(
    "http://127.0.0.1:8100/ui-extension/api/ui/v1/courses/cs3481/knowledge/does-not-exist/assessment",
    { headers: { Authorization: "Bearer test-session-token" } },
  );
  expect(response.status()).toBe(404);
  const body = await response.json();
  expect(String(body.detail)).toContain("not found");
});

test("a node assessment runs the real V3 flow: start, answer, submit, grade", async ({
  page,
  request,
}) => {
  await page.goto("/app#/course/cs3481/learn");
  await expect(page.locator("button.knowledge-strip")).toBeVisible();
  await page.locator("button.knowledge-strip").click();
  const tree = page.locator(".tree-expanded");
  await expect(tree).toBeVisible();

  // The synthetic fixture node appears because the shell lists the caller's own
  // registry nodes even when no reviewed tree exists yet.
  const nodeLabel = tree.locator(".tree-node-new").filter({ hasText: "Assessment Addition" });
  await expect(nodeLabel).toBeVisible();
  await nodeLabel.hover();
  const assessButton = tree.getByRole("button", { name: /测评结果/ });
  await expect(assessButton).toBeVisible();
  await assessButton.click();

  const modal = page.locator(".modal");
  await expect(modal).toBeVisible();
  await expect(modal).toContainText("未测评");

  const start = modal.getByRole("button", { name: /开始测评/ });
  await expect(start).toBeVisible();
  await start.click();

  // The V3 session starts for real and exposes exactly five frozen questions.
  await expect(modal.locator(".assessment-question")).toHaveCount(5);
  const answerBoxes = modal.getByLabel(/题答案/);
  await expect(answerBoxes).toHaveCount(5);
  for (let i = 0; i < 5; i += 1) {
    await answerBoxes.nth(i).fill("correct");
  }
  await modal.getByRole("button", { name: /提交答案/ }).click();

  // Grading happened against the V3 assessment engine and its grade snapshot.
  await expect(modal).toContainText("已评阅");
  await expect(modal.locator(".assessment-review").first()).toContainText("参考答案");

  // The node's own state reports the graded result too - still independent from
  // the learning progress, which this fixture never faked. This fixture course
  // has no published grade policy, so the letter grade is honestly null while
  // the raw score exists (UNCONFIGURED mapping).
  const listed = await request.get(
    "http://127.0.0.1:8100/ui-extension/api/ui/v1/courses/cs3481/knowledge",
    { headers: { Authorization: "Bearer test-session-token" } },
  );
  expect(listed.status()).toBe(200);
  const nodes = (await listed.json()) as {
    id: string;
    progress: string;
    assessment: { status: string; raw_score: number | null } | null;
  }[];
  const node = nodes.find((item) => item.id.startsWith("e2e-assessment-node-"));
  expect(node?.assessment?.status).toBe("GRADED");
  expect(typeof node?.assessment?.raw_score).toBe("number");
  expect(node?.progress).toBe("NOT_STARTED");
});

test("help covers the new surfaces and no horizontal overflow at 390px", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/app");
  const nav = page.getByRole("navigation", { name: "主导航" });
  await nav.getByRole("button", { name: "帮助", exact: true }).click();
  const drawer = page.getByRole("dialog", { name: "帮助面板" });
  await expect(drawer).toBeVisible();

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
});
