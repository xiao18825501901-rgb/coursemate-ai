import { expect, test } from "@playwright/test";


test("streams a cited course answer and adds it to the study plan", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") consoleErrors.push(message.text());
  });

  await page.goto("/qa/ge2324");
  await expect(page.getByRole("heading", { level: 1, name: "Ask your material" })).toBeVisible();
  await expect(page.getByLabel("Course", { exact: true })).toHaveValue("ge2324");
  await expect(page.getByText("assignment_2.pdf", { exact: true })).toBeVisible();

  await page.getByLabel("Ask a course question").fill(
    "What does Assignment 2 ask students to do with K-means and colors?",
  );
  await page.getByRole("button", { name: "Ask" }).click();
  await expect(page.getByText(/Based on the selected course material:/)).toBeVisible();
  await expect(page.locator(".message-assistant > p")).toContainText("K-means");
  await expect(page.getByText("assignment_2.pdf", { exact: true }).first()).toBeVisible();
  await page.screenshot({ path: "work/qa-desktop.png", fullPage: true });

  await page.getByRole("button", { name: /Add to study plan/i }).click();
  await page.getByRole("link", { name: "Study plan" }).click();
  await expect(page.getByRole("heading", { level: 3, name: /Review: What does Assignment 2/i }).last()).toBeVisible();
  expect(consoleErrors).toEqual([]);
});

test("natural-language agent chat creates a validated persistent task", async ({ page }) => {
  const title = `GE2324 browser acceptance ${Date.now()}`;
  await page.goto("/tasks");
  await page.getByLabel("Message the study agent").fill(
    `Add a high priority ${title} due 2026-08-20`,
  );
  await page.getByRole("button", { name: "Send" }).click();

  await expect(page.getByText(/requested task action completed/i)).toBeVisible();
  const card = page.getByRole("heading", {
    level: 3,
    name: title,
  });
  await expect(card).toBeVisible();
  const article = card.locator("xpath=ancestor::article");
  await expect(article.getByText("high priority", { exact: true })).toBeVisible();
  await expect(article.getByLabel(/Due date for/i)).toHaveValue("2026-08-20");
});

test("mobile navigation and core actions remain usable at 390 pixels", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: /Study from evidence/i })).toBeVisible();
  await expect(page.getByRole("link", { name: "Ask CourseMate" })).toBeVisible();
  await page.getByRole("link", { name: "Study plan", exact: true }).click();
  await expect(page.getByLabel("Message the study agent")).toBeVisible();
  await expect(page.getByRole("button", { name: "Send" })).toBeVisible();
  await page.screenshot({ path: "work/tasks-mobile.png", fullPage: true });
});
