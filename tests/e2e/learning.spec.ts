import { expect, test } from "@playwright/test";

test("V3 problem step teaches and returns across browser contexts", async ({ page, browser }) => {
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
  await page.getByText("建立私人知识教学范围（不发布官方树）", { exact: true }).click();
  await page.getByLabel("新私人知识节点").fill("Addition");
  await page.getByRole("button", { name: "建立私人教学范围" }).click();
  await expect(page.getByLabel("当前知识节点")).toContainText("Addition");
  await page.getByLabel("题目内容").fill("What is 2 + 3?");
  await page.getByRole("button", { name: "获取完整解答" }).click();
  await expect(page.getByText("[FAKE TEST FIXTURE] 2 + 3 = 5.", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Why do we add these counts?" }).click();
  await expect(page.getByText("原题条件", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "继续一个教学单元" }).click();
  await expect(page.getByText("LEARNED", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "返回原题原 Step" }).click();
  await expect(page.locator("article.solution-step:focus")).toBeVisible();
  await page.reload();
  await expect(page.getByText("LEARNED", { exact: true })).toBeVisible();
  const context = await browser.newContext();
  const reopened = await context.newPage();
  await reopened.goto("/learn/cs3481");
  await expect(reopened.getByText("LEARNED", { exact: true })).toBeVisible();
  await reopened.setViewportSize({ width: 375, height: 812 });
  await expect(reopened.getByRole("heading", { name: "题目应对", exact: true })).toBeVisible();
  expect(await reopened.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await reopened.screenshot({ path: "work/v3-mobile.png", fullPage: true });
  await page.screenshot({ path: "work/v3-desktop.png", fullPage: true });
  await context.close();
  expect(browserErrors).toEqual([]);
  expect(failedRequests).toEqual([]);
});
