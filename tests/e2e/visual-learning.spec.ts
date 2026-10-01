import { expect, test } from "@playwright/test";

test("visual assistance is opt-in, persists per course, and can be disabled", async ({ page }) => {
  await page.goto("/app#/course/cs3481/learn");
  const pane = page.locator(".learning-pane.pane-teach");
  await expect(pane).toBeVisible();
  const preference = page.getByRole("button", { name: "图片/视频辅助 · 关闭" });
  await expect(preference).toBeVisible();

  await page.getByLabel("知识学习输入").fill("Explain a gravitational lens using course evidence.");
  await page.getByRole("button", { name: "发送知识问题" }).click();
  const answer = pane.locator(".chat-message-new.assistant").last();
  await expect(answer).toBeVisible({ timeout: 30_000 });
  await expect(answer.getByRole("button", { name: "生成图片" })).toBeVisible();

  await answer.getByRole("button", { name: "生成图片" }).click();
  await expect(page.getByText("启用图片/视频辅助教学？")).toBeVisible();
  await expect(page.getByText(/文字回答仍会优先显示/)).toBeVisible();
  await expect(answer.getByText(/等待生成|正在规划|正在生成/)).toHaveCount(0);
  await page.getByRole("button", { name: "确认启用" }).click();
  await expect(page.getByRole("button", { name: "图片/视频辅助 · 已启用" })).toBeVisible();
  await expect(answer.getByText(/已完成|已从安全缓存恢复/)).toBeVisible({ timeout: 30_000 });
  const image = answer.locator(".visual-asset-card img");
  await expect(image).toBeVisible();
  await expect(image).toHaveAttribute("alt", /supported concept/i);

  await page.reload();
  await expect(page.getByRole("button", { name: "图片/视频辅助 · 已启用" })).toBeVisible();
  const restored = pane.locator(".chat-message-new.assistant").last();
  await expect(restored.getByText(/已完成|已从安全缓存恢复/)).toBeVisible({ timeout: 30_000 });
  await expect(restored.locator(".visual-asset-card img")).toBeVisible();

  await page.getByRole("button", { name: "图片/视频辅助 · 已启用" }).click();
  await expect(page.getByRole("button", { name: "图片/视频辅助 · 关闭" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("button", { name: "图片/视频辅助 · 关闭" })).toBeVisible();
});
