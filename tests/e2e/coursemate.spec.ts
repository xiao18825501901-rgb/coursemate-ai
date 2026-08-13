import { expect, test } from "@playwright/test";


test("keeps answers course-scoped, persists across a fresh login context, and adds one to the plan", async ({ browser, page }) => {
  test.setTimeout(60_000);
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") consoleErrors.push(message.text());
  });

  await page.goto("/qa/cs3481");
  await expect(page.getByRole("heading", { level: 1, name: "Ask your material" })).toBeVisible();
  const courseSelect = page.getByLabel("Course", { exact: true });
  await expect(courseSelect).toHaveValue("cs3481");

  const questions = [
    "How does DBSCAN identify a core point?",
    "Why does MinPts matter in DBSCAN?",
    "Give me a small DBSCAN example.",
  ];
  const askButton = page.getByRole("button", { name: "Ask", exact: true });
  for (const [index, question] of questions.entries()) {
    await page.getByLabel("Ask a course question").fill(question);
    await expect(askButton).toBeEnabled();
    await askButton.click();
    await expect(page.locator(".message-assistant")).toHaveCount(index + 1);
    await expect(page.getByRole("button", { name: /Add to study plan/i })).toHaveCount(index + 1);
  }
  await expect(page.locator(".message-user")).toHaveCount(3);
  await expect(page.locator(".message-assistant > p").first()).toContainText("DBSCAN");
  await expect(page.locator(".citation-list").first()).toBeVisible();

  const persistedConversationUrl = page.url();
  await page.reload();
  await expect(page.locator(".message-user")).toHaveCount(3);
  await expect(page.locator(".message-assistant")).toHaveCount(3);
  await expect(page.locator(".message-assistant > p").first()).toContainText("DBSCAN");
  await expect(page.locator(".citation-list").first()).toBeVisible();
  const reopenedContext = await browser.newContext();
  const reopenedPage = await reopenedContext.newPage();
  await reopenedPage.goto(persistedConversationUrl);
  await expect(reopenedPage.locator(".message-user")).toHaveCount(3);
  await expect(reopenedPage.locator(".message-assistant")).toHaveCount(3);
  await expect(reopenedPage.locator(".message-assistant > p").first()).toContainText("DBSCAN");
  await reopenedContext.close();

  await courseSelect.selectOption("ge2324");
  await expect(page).toHaveURL(/\/qa\/ge2324$/);
  await expect(courseSelect).toHaveValue("ge2324");
  await expect(page.getByText("assignment_2.pdf", { exact: true })).toBeVisible();

  await page.getByLabel("Ask a course question").fill(
    "What does Assignment 2 ask students to do with K-means and colors?",
  );
  await page.getByRole("button", { name: "Ask", exact: true }).click();
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

test("creates, indexes, teaches from, and deletes a private course", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (entry) => {
    if (entry.type() === "error" || entry.type() === "warning") consoleErrors.push(entry.text());
  });
  const courseId = `browser-course-${Date.now()}`;
  const courseName = `Browser Private Course ${courseId}`;

  await page.goto("/courses");
  await expect(page.getByRole("heading", { name: "Official Courses" })).toBeVisible();
  await page.getByRole("link", { name: "Create Course" }).click();
  await page.getByLabel("Course ID").fill(courseId);
  await page.getByLabel("Course name").fill(courseName);
  await page.getByLabel("Description").fill("A private end-to-end course.");
  await page.getByRole("button", { name: "Create private course" }).click();

  await expect(page).toHaveURL(new RegExp(`/qa/${courseId}$`));
  await expect(
    page.getByRole("complementary", { name: "Course documents" }).getByRole("strong"),
  ).toHaveText(courseName);
  await page.getByRole("link", { name: "Manage course and sources" }).click();
  await expect(page.getByText(/not visible to other students/i)).toBeVisible();
  await page.getByLabel("Upload course material").setInputFiles({
    name: "private-notes.md",
    mimeType: "text/markdown",
    buffer: Buffer.from("# Private topic\n\nThe private answer is evidence-bound."),
  });
  await expect(page.getByRole("status")).toContainText("Indexed");
  await expect(page.getByText("private-notes.md", { exact: true })).toBeVisible();
  await page.getByLabel("Learning and teaching requirements").fill(
    "I am a beginner. Explain why first, then show a worked example.",
  );
  await page.getByRole("button", { name: "Build profile preview" }).click();
  await expect(page.getByLabel("Teaching profile preview")).toBeVisible();
  await page.getByRole("button", { name: "Save as new version" }).click();
  await expect(page.getByText(/new conversations use v1/i)).toBeVisible();
  await page.getByLabel(/I want to publish and share/i).check();
  await page.getByLabel(/I confirm I have permission/i).check();
  await page.getByRole("button", { name: "Submit for admin review" }).click();
  await expect(page.getByText("Review pending")).toBeVisible();
  await page.screenshot({ path: "work/private-course-desktop.png", fullPage: true });

  await page.getByRole("link", { name: "Open tutor" }).click();
  await page.getByLabel("Ask a course question").fill("What is the private answer?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await expect(page.locator(".message-assistant > p").last()).toContainText("private answer");

  await page.goto(`/courses/${courseId}/settings`);
  await page.getByLabel(`Type ${courseId} to confirm`).fill(courseId);
  await page.getByRole("button", { name: "Delete course permanently" }).click();
  await expect(page).toHaveURL(/\/courses$/);
  await expect(page.getByText(courseName, { exact: true })).not.toBeVisible();
  expect(consoleErrors).toEqual([]);
});
