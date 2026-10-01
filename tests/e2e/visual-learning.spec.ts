import { expect, test } from "@playwright/test";

test("a real teaching answer creates and restores a protected Phase-A visual", async ({ page }) => {
  await page.goto("/app#/course/cs3481/learn");
  const pane = page.locator(".learning-pane.pane-teach");
  await expect(pane).toBeVisible();

  await page.getByLabel("知识学习输入").fill("Explain a gravitational lens using course evidence.");
  await page.getByRole("button", { name: "发送知识问题" }).click();
  const answer = pane.locator(".chat-message-new.assistant").last();
  await expect(answer).toBeVisible({ timeout: 30_000 });
  await expect(answer.getByRole("button", { name: "生成视觉" })).toBeVisible();

  await answer.getByRole("button", { name: "生成视觉" }).click();
  await expect(answer.getByText(/已完成|已从安全缓存恢复/)).toBeVisible({ timeout: 30_000 });
  const image = answer.locator(".visual-asset-card img");
  await expect(image).toBeVisible();
  await expect(image).toHaveAttribute("alt", /supported concept/i);

  await page.reload();
  const restored = pane.locator(".chat-message-new.assistant").last();
  await expect(restored.getByText(/已完成|已从安全缓存恢复/)).toBeVisible({ timeout: 30_000 });
  await expect(restored.locator(".visual-asset-card img")).toBeVisible();
});
