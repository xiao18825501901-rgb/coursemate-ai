import { expect, test } from "@playwright/test";


test("keeps answers course-scoped, streams citations, and adds one to the plan", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") consoleErrors.push(message.text());
  });

  await page.goto("/qa/cs3481");
  await expect(page.getByRole("heading", { level: 1, name: "Ask your material" })).toBeVisible();
  const courseSelect = page.getByLabel("Course", { exact: true });
  await expect(courseSelect).toHaveValue("cs3481");

  await page.getByLabel("Ask a course question").fill(
    "How does DBSCAN identify a core point?",
  );
  await page.getByRole("button", { name: "Ask" }).click();
  await expect(page.locator(".message-assistant > p").first()).toContainText("DBSCAN");
  await expect(page.locator(".citation-list").first()).toBeVisible();

  await courseSelect.selectOption("ge2324");
  await expect(page).toHaveURL(/\/qa\/ge2324$/);
  await expect(courseSelect).toHaveValue("ge2324");
  await expect(page.getByText("assignment_2.pdf", { exact: true })).toBeVisible();

  await page.getByLabel("Ask a course question").fill(
    "What does Assignment 2 ask students to do with K-means and colors?",
  );
  await page.getByRole("button", { name: "Ask" }).click();
  await expect(page.getByText(/Based on the selected course material:/)).toBeVisible();
  const assignmentAnswer = page.locator(".message-assistant").last();
  await expect(assignmentAnswer.locator(":scope > p")).toContainText("K-means");
  await expect(
    assignmentAnswer.getByLabel("Answer sources").locator("details").first(),
  ).toContainText("assignment_2.pdf");
  await page.screenshot({ path: "work/qa-desktop.png", fullPage: true });

  await page.getByRole("button", { name: /Add to study plan/i }).last().click();
  await page.getByRole("link", { name: "Study plan" }).click();
  await expect(page.getByRole("heading", { level: 3, name: /Review: What does Assignment 2/i }).last()).toBeVisible();
  expect(consoleErrors).toEqual([]);
});

test("agent-created tasks remain editable and can be completed", async ({ page }) => {
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

  await article.getByLabel(`Due date for ${title}`).fill("2026-08-25");
  await expect(article.getByLabel(`Due date for ${title}`)).toHaveValue("2026-08-25");
  await article.getByLabel(`Priority for ${title}`).selectOption("medium");
  await expect(article.getByText("medium priority", { exact: true })).toBeVisible();
  await article.getByRole("button", { name: "Mark complete" }).click();

  const completedColumn = page.getByRole("heading", { level: 2, name: "Completed" })
    .locator("xpath=ancestor::section");
  await expect(completedColumn.getByRole("heading", { level: 3, name: title })).toBeVisible();
  await expect(completedColumn.getByRole("button", { name: "Reopen" })).toBeVisible();
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
