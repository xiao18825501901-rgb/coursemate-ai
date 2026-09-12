import { expect, test } from "@playwright/test";

test("V3 private image problem teaches and returns across browser contexts", async ({ page, browser }) => {
  test.setTimeout(60_000);
  const browserErrors: string[] = [];
  const failedRequests: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") browserErrors.push(message.text());
  });
  page.on("pageerror", (error) => browserErrors.push(error.message));
  page.on("requestfailed", (request) => {
    failedRequests.push(`${request.method()} ${request.url()} ${request.failure()?.errorText ?? ""}`);
  });
  await page.goto("/learn/cs3481");
  await expect(page.getByRole("heading", { name: "协同学习工作区" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "课程知识树" })).toBeVisible();
  await expect(page.getByText("尚无已审核发布的官方树", { exact: true })).toBeVisible();
  await expect(page.getByText("尚未建立个人学习树", { exact: true })).toBeVisible();
  await page.getByText("课程文件与我的私人资料", { exact: true }).click();
  await page.getByLabel("添加私人资料").setInputFiles({
    name: "scores.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("name,value\nalice,=2+2\n"),
  });
  await page.getByRole("button", { name: "预览 scores.csv" }).click();
  await expect(page.getByRole("table", { name: "scores.csv 表格预览" })).toBeVisible();
  await expect(page.getByText("=2+2", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "关闭预览" }).click();
  await page.getByLabel("添加私人资料").setInputFiles({
    name: "question.png",
    mimeType: "image/png",
    buffer: Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
      "base64",
    ),
  });
  await page.getByText("建立私人知识教学范围（不发布官方树）", { exact: true }).click();
  await page.getByLabel("新私人知识节点").fill("Addition");
  await page.getByRole("button", { name: "建立私人教学范围" }).click();
  await expect(page.getByLabel("当前知识节点")).toContainText("Addition");
  await page.getByText("建立或更新个人学习树", { exact: true }).click();
  await page.getByLabel("选择 Addition").check();
  await page.getByRole("button", { name: "建立个人学习树" }).click();
  await expect(page.getByLabel("我的个性化树").getByText("ACTIVE", { exact: true })).toBeVisible();
  await expect(page.getByLabel("我的个性化树").getByText("NOT_ASSESSED", { exact: true })).toBeVisible();
  await page.getByRole("radio", { name: "私人题目图片" }).check();
  await page.getByLabel("已授权 PNG/JPEG").selectOption({ index: 1 });
  await page.getByLabel("给转录的提示（可选，不视为已核验题干）").fill("What is 2 + 3?");
  await page.getByLabel("解题要求").fill("Please solve the question in this image.");
  await page.getByRole("button", { name: "获取完整参考解答" }).click();
  await expect(page.getByText("[FAKE TEST FIXTURE] What is 2 + 3?", { exact: true })).toBeVisible();
  await expect(page.getByText("[FAKE TEST FIXTURE] Visual correctness was not evaluated.", { exact: true })).toBeVisible();
  await expect(page.getByText("[FAKE TEST FIXTURE] 2 + 3 = 5.", { exact: true })).toBeVisible();
  await expect(page.getByText("公式 / 计算：2 + 3 = 5", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Why do we add these counts?" }).click();
  await expect(page.getByText("原题条件", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "继续一个教学单元" }).click();
  await expect(page.locator(".learning-toolbar").getByText("LEARNED", { exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "理解检查" })).toBeVisible();
  await expect(page.getByText(/ciallo State the idea in your own words/)).toBeVisible();
  await expect(page.getByText(/Teaching Plan v1 · 本次新建/)).toBeVisible();
  await page.getByRole("button", { name: "返回原题原 Step" }).click();
  await expect(page.locator("article.solution-step:focus")).toBeVisible();
  await page.reload();
  await expect(page.locator(".learning-toolbar").getByText("LEARNED", { exact: true })).toBeVisible();
  const context = await browser.newContext();
  const reopened = await context.newPage();
  await reopened.goto("/learn/cs3481");
  await expect(reopened.locator(".learning-toolbar").getByText("LEARNED", { exact: true })).toBeVisible();
  await expect(reopened.getByLabel("我的个性化树").getByText("LEARNED", { exact: true })).toBeVisible();
  await reopened.setViewportSize({ width: 375, height: 812 });
  await expect(reopened.getByRole("heading", { name: "题目应对", exact: true })).toBeVisible();
  expect(await reopened.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await reopened.screenshot({ path: "work/v3-mobile.png", fullPage: true });
  await page.screenshot({ path: "work/v3-desktop.png", fullPage: true });
  await context.close();
  await page.getByText("建立或更新个人学习树", { exact: true }).click();
  await page.getByRole("button", {
    name: "Assessment Grade NOT_ASSESSED for Assessment Addition",
  }).click();
  await expect(page.locator("#assessment-panel").getByText("Assessment Addition", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "开始五题测评" }).click();
  await expect(page.getByText("总分 100 · 五题不等权", { exact: true })).toBeVisible();
  for (let ordinal = 1; ordinal <= 5; ordinal += 1) {
    await page.getByLabel(`回答第 ${ordinal} 题`).fill("correct");
  }
  await page.getByRole("button", { name: "提交测评" }).click();
  await expect(page.getByRole("heading", { name: "Raw Score：100 / 100" })).toBeVisible();
  await expect(page.getByText("评分映射待配置", { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Raw Score：100 / 100" })).toBeVisible();
  await page.screenshot({ path: "work/v3-assessment-desktop.png", fullPage: true });
  await page.setViewportSize({ width: 375, height: 812 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: "work/v3-assessment-mobile.png", fullPage: true });
  expect(browserErrors).toEqual([]);
  expect(failedRequests).toEqual([]);
});
