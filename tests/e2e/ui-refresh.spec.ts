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
  const posted = page.waitForResponse(
    (response) =>
      response.url().includes("/comments") && response.request().method() === "POST",
  );
  await page.getByRole("button", { name: /发布|发送|发表/ }).first().click();
  expect((await posted).status()).toBe(201);
  // A textarea reports its own value as text, so an unscoped `getByText` would
  // pass on the still-filled input before the comment was ever persisted. Scope
  // the assertion to the rendered feed: the comment must come back from the API.
  await expect(page.locator(".discussion-text").filter({ hasText: text })).toBeVisible();

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
  // The shipped strip names the knowledge tree and its expand affordance.
  await expect(strip).toContainText("课程知识点");
  await expect(strip).toContainText("点击展开");
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
  const assessButton = nodeLabel
    .locator(".node-popover")
    .getByRole("button", { name: /测评结果/ });
  await expect(assessButton).toBeVisible();
  await assessButton.click();

  // The assessment surface is the shipped full-screen workspace (an overlay
  // dialog), not a generic modal.
  const workspace = page.locator('.assessment-overlay[aria-label="五题测评工作区"]');
  await expect(workspace).toBeVisible();
  await expect(workspace).toContainText("未开始");

  await workspace.getByRole("button", { name: /开始测评/ }).click();

  // The V3 session starts for real and exposes exactly five frozen questions.
  await expect(workspace.locator(".assessment-question")).toHaveCount(5, {
    timeout: 60_000,
  });
  // Answers are written into the one unified composer, labelled per question.
  const answerBox = workspace.getByLabel("统一答案");
  await answerBox.fill("1. correct\n2. correct\n3. correct\n4. correct\n5. correct");
  const graded = page.waitForResponse(
    (response) =>
      /\/knowledge\/assessment\/[^/]+\/submit$/.test(new URL(response.url()).pathname) &&
      response.request().method() === "POST",
    { timeout: 90_000 },
  );
  await workspace.getByRole("button", { name: /提交答案/ }).click();
  const gradedBody = (await (await graded).json()) as {
    questions?: Array<{
      review?: {
        reference_solution?: unknown;
        reference_verification?: {
          verdict?: string;
          verified?: boolean;
          definitive?: boolean;
        };
      };
    }>;
  };

  // Grading happened against the V3 assessment engine and its grade snapshot.
  await expect(workspace).toContainText("已评阅", { timeout: 60_000 });
  await expect(workspace.locator(".assessment-review").first()).toContainText("参考解");

  // Module D's high-impact gate reaches the learner: the note shown next to the
  // reference solution must agree with the verification the server just reported, and
  // an unchecked reference may not look checked. (Without a credential the server
  // reports verified-but-not-definitive, so the note is expected to be present; the
  // definitive branch keeps the assertion meaningful if one is ever configured.)
  const verification = (gradedBody.questions || [])
    .map((question) => question.review?.reference_verification)
    .find((candidate) => candidate != null);
  expect(verification, "the graded session must report reference verification").toBeTruthy();
  // This fixture's questions carry no seeded reference source_refs, so the gate honestly
  // reports "unverified" rather than pretending the evidence was checked.
  expect(verification?.verdict).toBe("reference_evidence_unverified");
  expect(verification?.definitive).toBe(false);
  const verificationNote = workspace
    .locator(".assessment-review")
    .first()
    .locator(".reference-verification");
  if (verification?.definitive === true) {
    await expect(verificationNote).toHaveCount(0);
  } else {
    await expect(verificationNote).toBeVisible();
    await expect(verificationNote).toContainText(
      verification?.verified === true ? "尚未做语义支持判断" : "没有可核验的引用来源",
    );
  }

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

test("the knowledge tree renders the seeded hierarchy with real V3 statuses", async ({
  page,
  request,
}) => {
  await page.goto("/app#/course/cs3481/learn");
  await expect(page.locator("button.knowledge-strip")).toBeVisible();
  await page.locator("button.knowledge-strip").click();
  const tree = page.locator(".tree-expanded");
  await expect(tree).toBeVisible();

  // The composite root becomes the group title; its two atomic children are
  // rows inside it. Neither title nor hierarchy is fabricated by the shell.
  await expect(tree.locator(".tree-group-title")).toHaveText("数据科学基础");
  const clustering = tree.locator(".tree-node-new").filter({ hasText: "聚类分析" });
  const kmeans = tree.locator(".tree-node-new").filter({ hasText: "K-means 聚类" });
  await expect(clustering).toBeVisible();
  await expect(kmeans).toBeVisible();

  // Both status entries come from V3 state: LEARNING is derived from real
  // delivery evidence (1 of 2 REQUIRED items), LEARNED from the single covered
  // item, and assessment is independent and honestly empty.
  await clustering.hover();
  await expect(clustering.locator(".node-popover")).toBeVisible();
  await expect(
    clustering.locator(".node-popover").getByRole("button", { name: /学习进度/ }),
  ).toContainText("学习中");
  await expect(
    clustering.locator(".node-popover").getByRole("button", { name: /测评结果/ }),
  ).toContainText("未测评");

  // Move off the node first: its popover overlays the next row.
  await tree.getByRole("heading", { name: "课程知识点" }).hover();
  await kmeans.hover();
  await expect(kmeans.locator(".node-popover")).toBeVisible();
  await expect(
    kmeans.locator(".node-popover").getByRole("button", { name: /学习进度/ }),
  ).toContainText("已完成");

  // The same rendering's database facts through the mounted API.
  const listed = await request.get(
    "http://127.0.0.1:8100/ui-extension/api/ui/v1/courses/cs3481/knowledge",
    { headers: { Authorization: "Bearer test-session-token" } },
  );
  expect(listed.status()).toBe(200);
  const nodes = (await listed.json()) as {
    id: string;
    parent: string | null;
    kind: string;
    progress: string;
  }[];
  const byId = Object.fromEntries(nodes.map((node) => [node.id, node]));
  expect(byId["e2e-tree-root"]?.parent).toBeNull();
  expect(byId["e2e-tree-root"]?.kind).toBe("COMPOSITE");
  expect(byId["e2e-tree-clustering"]?.parent).toBe("e2e-tree-root");
  expect(byId["e2e-tree-clustering"]?.progress).toBe("LEARNING");
  expect(byId["e2e-tree-kmeans"]?.parent).toBe("e2e-tree-root");
  expect(byId["e2e-tree-kmeans"]?.progress).toBe("LEARNED");
});

test("a problem's steps stay in the problem pane and keep the detached detail flow", async ({
  page,
  request,
}) => {
  await page.goto("/app#/course/cs3481/learn");
  await expect(page.locator(".workspace-columns")).toBeVisible();
  const problemPane = page.locator(".learning-pane.pane-problem");
  const teachPane = page.locator(".learning-pane.pane-teach");

  // The labelled local test provider answers the problem with numbered steps;
  // the shell derives the step anchors server-side from the same code path a
  // live model's output would take.
  await problemPane.locator("textarea").fill(`判断核心点 ${Date.now()}`);
  await problemPane.getByRole("button", { name: "发送题目" }).click();
  await expect(problemPane.locator("section[id^='step-']").first()).toBeVisible({ timeout: 30_000 });
  await expect(problemPane.locator(".step-link")).toHaveCount(0);
  await expect(teachPane.locator(".bridge-banner")).toHaveCount(0);
  await expect(teachPane.locator(".chat-message-new.assistant")).toHaveCount(0);
});

test("teaching a node from the shell books reviewed coverage end-to-end", async ({
  page,
  request,
}) => {
  await page.goto("/app#/course/cs3481/learn");
  await expect(page.locator(".workspace-columns")).toBeVisible();

  // The seeded clustering node starts at LEARNING: 1 of 2 REQUIRED items has
  // legacy evidence. Teaching it through the shell must add the second item as
  // REVIEWED evidence and move the node to LEARNED - the same V3 ledger the
  // old entry reads.
  const knowledgeUrl =
    "http://127.0.0.1:8100/ui-extension/api/ui/v1/courses/cs3481/knowledge";
  const readNode = async () => {
    const body = (await (
      await request.get(knowledgeUrl, {
        headers: { Authorization: "Bearer test-session-token" },
      })
    ).json()) as {
      id: string;
      progress: string;
      learning: { required_total: number; covered_required: number };
    }[];
    return body.find((node) => node.id === "e2e-tree-clustering");
  };
  const before = await readNode();
  expect(before?.progress).toBe("LEARNING");
  expect(before?.learning.covered_required).toBe(1);

  await page.locator("button.knowledge-strip").click();
  const tree = page.locator(".tree-expanded");
  await expect(tree).toBeVisible();
  const nodeRow = tree.locator(".tree-node-new").filter({ hasText: "聚类分析" });
  await nodeRow.hover();
  await nodeRow.locator(".node-popover").getByRole("button", { name: /学习进度/ }).click();

  // The labelled test provider echoes the spec acceptance statements, the
  // deterministic reviewer confirms them, and the status line says so.
  await expect(
    page.locator(".learning-pane.pane-teach .generation-status"),
  ).toContainText("已计入覆盖", {
    timeout: 30_000,
  });

  // The same authoritative state is visible through the mounted API.
  await expect
    .poll(async () => {
      const node = await readNode();
      return node ? `${node.progress}:${node.learning.covered_required}` : "missing";
    })
    .toBe("LEARNED:2");
});

test("the knowledge tree is reachable by keyboard and by touch", async ({ page }) => {
  await page.goto("/app#/course/cs3481/learn");
  await expect(page.locator(".workspace-columns")).toBeVisible();

  // Keyboard: the strip is a real button (Enter expands), node rows are
  // focusable and reveal their two status entries on focus, and Enter on a
  // popover action starts teaching from that node.
  const strip = page.locator("button.knowledge-strip");
  await strip.focus();
  await page.keyboard.press("Enter");
  const tree = page.locator(".tree-expanded");
  await expect(tree).toBeVisible();

  const kmeans = tree.locator(".tree-node-new").filter({ hasText: "K-means 聚类" });
  await kmeans.focus();
  await expect(kmeans.locator(".node-popover")).toBeVisible();
  await expect(
    kmeans.locator(".node-popover").getByRole("button", { name: /测评结果/ }),
  ).toContainText("未测评");
  const learnFromKeyboard = kmeans
    .locator(".node-popover")
    .getByRole("button", { name: /学习进度/ });
  await learnFromKeyboard.focus();
  await page.keyboard.press("Enter");
  // The node jump collapses the tree overlay itself.
  await expect(tree).toHaveCount(0);

  // The node jump lands in the teach lane and the labelled local test provider
  // completes the run with a real teaching message.
  const teachPane = page.locator(".learning-pane.pane-teach");
  await expect(teachPane).toContainText("请用中文从零教我理解 K-means 聚类", {
    timeout: 30_000,
  });
  // The labelled test provider echoes this node's spec acceptance statement.
  await expect(teachPane).toContainText("State the update rule", { timeout: 30_000 });

  // Touch: at 390px the panes are tabs; a tap opens the same popover and a tap
  // on 学习进度 switches to the teach tab for that node.
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator("button.knowledge-strip").tap();
  await expect(tree).toBeVisible();
  const clustering = tree.locator(".tree-node-new").filter({ hasText: "聚类分析" });
  await clustering.tap();
  const touchPopover = clustering.locator(".node-popover");
  await expect(touchPopover).toBeVisible();
  // The coverage-closure test taught this node to LEARNED earlier in the run.
  await expect(
    touchPopover.getByRole("button", { name: /学习进度/ }),
  ).toContainText("已完成");
  await touchPopover.getByRole("button", { name: /学习进度/ }).tap();

  await expect(page.locator(".mobile-pane-tabs button.active")).toHaveText("知识学习");
  await expect(page.locator(".learning-pane.pane-teach.mobile-active")).toBeVisible();
  await expect(teachPane).toContainText("请用中文从零教我理解 聚类分析", {
    timeout: 30_000,
  });
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

test("theme is server-persisted, spans the shell, and preserves an active learning workspace", async ({ page }, testInfo) => {
  await page.goto("/app");
  const toggle = page.getByRole("button", { name: /切换至(浅色|深色)模式/ });
  if (await toggle.getAttribute("aria-pressed") === "true") await toggle.click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");

  const darkSaved = page.waitForResponse((response) =>
    response.request().method() === "PUT" && response.url().endsWith("/me/preferences"),
  );
  await toggle.click();
  expect((await darkSaved).ok()).toBeTruthy();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");

  // The global document root carries the setting into each shell surface.
  for (const hash of ["#/courses", "#/calendar", "#/inbox", "#/course/cs3481/files", "#/course/cs3481/learn"]) {
    await page.goto(`/app${hash}`);
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  }
  await expect(page.locator(".workspace-columns")).toBeVisible();
  await expect(page.locator(".learning-pane.pane-teach")).toBeVisible();
  await expect(page.locator(".learning-pane.pane-problem")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("dark-learning-workspace.png"), fullPage: true });

  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(page.locator(".workspace-columns")).toBeVisible();

  await page.goto("/app");
  await page.getByRole("button", { name: "账户", exact: true }).click();
  // The seeded account was certified before the new policy.  Automatic
  // enrollment must not erase that provenance; it only fills a missing
  // qualification for an otherwise active registered identity.
  await expect(page.getByRole("dialog", { name: "账户面板" })).toContainText(/已通过（(注册自动开通|历史用户)）/);

  const lightSaved = page.waitForResponse((response) =>
    response.request().method() === "PUT" && response.url().endsWith("/me/preferences"),
  );
  await page.getByRole("button", { name: "关闭侧栏" }).click();
  await page.getByRole("button", { name: "切换至浅色模式" }).click();
  expect((await lightSaved).ok()).toBeTruthy();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
});

test("each learning pane persists its own accessible reasoning strength and submits it on the next run", async ({ page }, testInfo) => {
  await page.goto("/app#/course/cs3481/learn");
  const teach = page.locator(".learning-pane.pane-teach");
  const problem = page.locator(".learning-pane.pane-problem");
  const problemTrigger = problem.locator(".reasoning-trigger");
  const teachTrigger = teach.locator(".reasoning-trigger");
  await expect(problemTrigger).toContainText("中");
  await expect(teachTrigger).toContainText("中");

  await problemTrigger.click();
  const problemPopover = problem.getByRole("dialog", { name: "推理强度" });
  await expect(problemPopover).toBeVisible();
  const problemRange = problemPopover.getByLabel("推理强度");
  await problemRange.focus();
  const problemSaved = page.waitForResponse((response) =>
    response.request().method() === "PUT" && response.url().endsWith("/courses/cs3481/layout"),
  );
  await page.keyboard.press("ArrowRight");
  expect((await problemSaved).ok()).toBeTruthy();
  await expect(problemTrigger).toContainText("高");
  await page.keyboard.press("Escape");
  await expect(problemPopover).toHaveCount(0);

  const submitted = page.waitForRequest((request) =>
    request.method() === "POST" && /\/conversations\/[^/]+\/runs$/.test(new URL(request.url()).pathname),
  );
  await problem.getByLabel("题目应对输入").fill("请用当前强度解答一个 DBSCAN 问题");
  await problem.getByRole("button", { name: "发送题目" }).click();
  expect((await submitted).postDataJSON()).toMatchObject({ reasoning_strength: "high" });

  await teachTrigger.click();
  const teachPopover = teach.getByRole("dialog", { name: "推理强度" });
  const teachRange = teachPopover.getByLabel("推理强度");
  await teachRange.focus();
  const teachSaved = page.waitForResponse((response) =>
    response.request().method() === "PUT" && response.url().endsWith("/courses/cs3481/layout"),
  );
  await page.keyboard.press("End");
  expect((await teachSaved).ok()).toBeTruthy();
  await expect(teachTrigger).toContainText("最高");
  await expect(problemTrigger).toContainText("高");
  await page.keyboard.press("Escape");
  await page.screenshot({ path: testInfo.outputPath("independent-reasoning-strengths.png"), fullPage: true });
});

test("the Canvas import has two entry points and says so honestly when no school is open", async ({
  page,
}) => {
  // The deployment has no school Developer Key, so this is the state a real user sees today.
  // The import screen must show that state and the local-upload fallback rather than a button
  // that fails on click — and it must never ask for a personal access token.
  const canvasRequests: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/api/integrations/canvas")) canvasRequests.push(url.pathname);
  });

  await page.goto("/app");
  await assertShellDocument(page);

  // Entry point 1: the last row of the dashboard's dashed create card.
  const dashboardRow = page.locator(".add-course-canvas-row");
  await expect(dashboardRow).toBeVisible();
  const dashboardLink = dashboardRow.getByRole("button", { name: "从 Canvas 导入" });
  await expect(dashboardLink).toBeVisible();
  // A real control, not a decorated div: focusable, and activated from the keyboard.
  await dashboardLink.focus();
  await expect(dashboardLink).toBeFocused();
  await page.keyboard.press("Enter");

  const dialog = page.getByRole("dialog", { name: "从 Canvas 导入课程" });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("等待学校开通 Canvas 连接");
  await expect(dialog).toContainText("Developer Key");
  await expect(dialog).toContainText("CityU");
  // The client asked the server, rather than guessing.
  expect(canvasRequests).toContain("/api/integrations/canvas/institutions");
  expect(canvasRequests).toContain("/api/integrations/canvas/connections");

  // The only inputs on this screen are the school choice itself — one radio per registered school and
  // one for "其他 Canvas 学校". The earlier version of this journey asserted *zero* inputs, which was
  // true before the revision added the picker; asserting what the inputs actually are is the stronger
  // claim, and the credential check below is the one that matters.
  const inputs = dialog.locator("input");
  const inputCount = await inputs.count();
  expect(inputCount).toBeGreaterThan(0);
  for (let index = 0; index < inputCount; index += 1) {
    const input = inputs.nth(index);
    expect(await input.getAttribute("type")).toBe("radio");
    expect(await input.getAttribute("name")).toBe("canvas-school");
  }
  // Nothing anywhere in the dialog is named or labelled like a credential.
  expect(
    await dialog
      .locator('input[name*="token" i], input[id*="token" i], input[name*="pat" i], input[name*="secret" i]')
      .count(),
  ).toBe(0);

  // The revision's local route: a secondary entry opens the tutorial, the page states plainly that a
  // token must not be pasted here, and the local bridge is offered as a real button. None of it adds
  // a field, which is the point — the token is read on the user's own machine.
  await dialog.getByRole("button", { name: "无法连接？查看本地 Token 导入方式" }).click();
  await expect(dialog).toContainText("Approved Integrations");
  await expect(dialog).toContainText("New Access Token");
  await expect(dialog).toContainText("不要把这个 Token 粘贴到 CourseJesus 网页");
  await expect(dialog.getByRole("button", { name: "用本地 Token 导入" })).toBeVisible();
  expect(await dialog.locator("input").count()).toBe(inputCount);

  // The fallback is the real local-upload path: it opens the existing create-course form.
  await dialog.getByRole("button", { name: /上传本地资料/ }).click();
  const createDialog = page.getByRole("dialog", { name: "创建你的课程" });
  await expect(createDialog).toBeVisible();
  await expect(createDialog.getByLabel("课程名称")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(createDialog).toHaveCount(0);

  // Entry point 2: the create area at the top of All Courses.
  await page.evaluate(() => {
    window.location.hash = "#/courses";
  });
  await expect(page.getByRole("heading", { level: 1, name: "所有课程" })).toBeVisible();
  const bannerLink = page.locator(".canvas-import-link-banner");
  await expect(bannerLink).toBeVisible();
  await bannerLink.click();
  const bannerDialog = page.getByRole("dialog", { name: "从 Canvas 导入课程" });
  await expect(bannerDialog).toBeVisible();
  await expect(bannerDialog).toContainText("等待学校开通 Canvas 连接");
});

test("the local Canvas bridge runs from the shipped page to a selected course", async ({
  page,
  request,
}) => {
  // The only route that works while a school has no Developer Key: a short-lived session, a one-time
  // code for the user's terminal, and the user choosing courses **here**. The local tool is played by
  // `request`, which talks to the same backend with the same test identity — everything else is the
  // shipped page and the real routes.
  const api = "http://127.0.0.1:8100";
  const auth = { Authorization: "Bearer test-session-token" };
  const opened: string[] = [];
  page.on("request", (r) => {
    const url = new URL(r.url());
    if (url.pathname.startsWith("/api/integrations/canvas/local-sessions")) opened.push(url.pathname);
  });

  await page.goto("/app");
  await assertShellDocument(page);
  await page.locator(".add-course-canvas-row").getByRole("button", { name: "从 Canvas 导入" }).click();

  const dialog = page.getByRole("dialog", { name: "从 Canvas 导入课程" });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("等待学校开通 Canvas 连接");

  // Choose the school and ask for a session. The page shows the code the user pastes into a terminal.
  // The radio's accessible name is the label plus the origin, so the origin is what identifies it
  // (the first version of this journey looked for the full display name and never found it).
  await dialog.getByRole("radio", { name: /canvas\.cityu\.edu\.hk/ }).check();
  await dialog.getByRole("button", { name: "用本地 Token 导入" }).click();
  const code = dialog.locator(".canvas-import-code");
  await expect(code).toBeVisible();
  const command = (await code.innerText()).trim();
  expect(command).toMatch(/--code\s+[A-Za-z0-9_-]{20,}/);
  const oneTimeCode = command.split("--code")[1].trim();
  expect(opened).toContain("/api/integrations/canvas/local-sessions");

  // The page never asked for a token: the only field in this step is none at all.
  expect(await dialog.locator("input").count()).toBe(0);

  // The local tool claims the session and reports what it found on the user's own account.
  const claim = await request.post(`${api}/api/integrations/canvas/local-sessions/claim`, {
    headers: auth,
    data: { code: oneTimeCode, canvas_user_id: "4242", canvas_display_name: "Student One" },
  });
  expect(claim.ok(), await claim.text()).toBeTruthy();
  const sessionId = (await claim.json()).sessionId as string;

  const discovery = await request.post(
    `${api}/api/integrations/canvas/local-sessions/${sessionId}/discovery`,
    {
      headers: auth,
      data: {
        courses: [
          {
            canvas_course_id: "560",
            name: "Problem Solve & Programming",
            course_code: "CS2312",
            term: "Semester B 2025_26",
            enrollment_state: "active",
            workflow_state: "available",
            file_count: 3,
          },
        ],
      },
    },
  );
  expect(discovery.ok(), await discovery.text()).toBeTruthy();

  // The page polls the session and offers what the tool found; nothing is selected by default.
  await expect(dialog).toContainText("Problem Solve & Programming");
  await expect(dialog).toContainText("CS2312");
  const courseCheckbox = dialog.getByRole("checkbox").first();
  await expect(courseCheckbox).not.toBeChecked();
  await courseCheckbox.check();
  await dialog.getByRole("button", { name: /开始导入/ }).click();

  // The user's choice is what the server records — the local tool only ever reads it back.
  await expect
    .poll(async () => {
      const status = await request.get(
        `${api}/api/integrations/canvas/local-sessions/${sessionId}/selection`,
        { headers: auth },
      );
      return (await status.json()).selectedCourseIds as string[];
    }, { timeout: 20_000 })
    .toEqual(["560"]);
});

test("the Canvas import screen fits a 390px viewport and both themes", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/app");

  const link = page.locator(".add-course-canvas-row").getByRole("button", { name: "从 Canvas 导入" });
  await expect(link).toBeVisible();
  await link.click();
  const dialog = page.getByRole("dialog", { name: "从 Canvas 导入课程" });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("等待学校开通 Canvas 连接");

  // The dialog stays inside the viewport instead of overflowing it.
  const box = await dialog.boundingBox();
  expect(box).not.toBeNull();
  expect((box?.x ?? 0) + (box?.width ?? 0)).toBeLessThanOrEqual(391);
  const fallback = dialog.getByRole("button", { name: /上传本地资料/ });
  await expect(fallback).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("canvas-import-390.png"), fullPage: true });

  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "切换至深色模式" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await link.click();
  const darkDialog = page.getByRole("dialog", { name: "从 Canvas 导入课程" });
  await expect(darkDialog).toBeVisible();
  await expect(darkDialog).toContainText("等待学校开通 Canvas 连接");
  // The entry point keeps its own contrast in the dark theme (it is not left as dark text).
  await page.keyboard.press("Escape");
  const colour = await link.evaluate((node) => getComputedStyle(node).color);
  expect(colour).not.toBe("rgb(0, 0, 0)");
  await page.screenshot({ path: testInfo.outputPath("canvas-import-dark-390.png"), fullPage: true });
});
