import { act, fireEvent, render, screen } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { Discussion } from "./pages.jsx";
import { LanguageControl, UiLocaleProvider } from "./UiLocale";

afterEach(() => vi.restoreAllMocks());

const originalRows = [{ id: "original-comment", parent: null, name: "用户 Qwen", author: "student",
  text: "用户原文讨论 DeepSeek 和 Qwen", created_at: "2026-10-03T12:00:00Z", likes: 0 },
  { id: "original-reply", parent: "original-comment", name: "回复者", author: "other",
    text: "原始回复，保持中文", created_at: "2026-10-03T12:01:00Z", likes: 1 }];

function mounted(rows = originalRows, visibility = "private") {
  localStorage.clear();
  vi.spyOn(Discussion.prototype, "load").mockImplementation(async function (this: any) {
    this.setState({ rows });
  });
  let instance: any;
  render(<UiLocaleProvider><LanguageControl /><Discussion
    ref={value => { instance = value; }} course={{ id: "original-course", visibility }}
    user={{ id: "student", name: "用户 Qwen" }} refresh={vi.fn()} toast={vi.fn()} />
  </UiLocaleProvider>);
  return instance;
}

test("discussion locale updates system copy and aria labels without altering original drafts or replies", () => {
  const page = mounted();
  fireEvent.change(screen.getByRole("textbox", { name: "课程评论" }),
    { target: { value: "我的 Qwen 评论草稿" } });
  fireEvent.click(screen.getAllByRole("button", { name: "回复" })[0]!);
  fireEvent.change(screen.getByRole("textbox", { name: "回复评论" }),
    { target: { value: "中文回复草稿" } });
  const originalState = page.state;
  const fetchSpy = vi.spyOn(globalThis, "fetch");
  fireEvent.click(screen.getByRole("button", { name: "English" }));
  expect(screen.getByRole("heading", { name: "Comments" })).toBeVisible();
  expect(screen.getByText("Private course discussion")).toBeVisible();
  expect(screen.getByRole("textbox", { name: "Course comment" })).toHaveValue("我的 Qwen 评论草稿");
  expect(screen.getByRole("textbox", { name: "Reply to comment" })).toHaveValue("中文回复草稿");
  expect(screen.getByRole("button", { name: "Post comment" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Send reply" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Like" })).toBeVisible();
  expect(screen.getByText("用户原文讨论 DeepSeek 和 Qwen")).toBeVisible();
  expect(screen.getByText("原始回复，保持中文")).toBeVisible();
  expect(page.state).toBe(originalState);
  expect(page.state.replyTo).toBe("original-comment");
  expect(page.props.course.id).toBe("original-course");
  fireEvent.click(screen.getByRole("button", { name: "中文" }));
  expect(screen.getByRole("textbox", { name: "课程评论" })).toHaveValue("我的 Qwen 评论草稿");
  expect(screen.getByRole("textbox", { name: "回复评论" })).toHaveValue("中文回复草稿");
  expect(page.state).toBe(originalState);
  expect(fetchSpy).not.toHaveBeenCalled();
});

test("public discussion empty state and deletion confirmation translate without modifying comments", () => {
  const page = mounted([], "public");
  fireEvent.click(screen.getByRole("button", { name: "English" }));
  expect(screen.getByText("Course discussion")).toBeVisible();
  expect(screen.getByRole("heading", { name: "Start the first discussion for this course" })).toBeVisible();
  expect(screen.getByText("Replies will appear in your inbox.")).toBeVisible();
  act(() => page.setState({ rows: originalRows }));
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  const fetchSpy = vi.spyOn(globalThis, "fetch");
  fireEvent.click(screen.getByRole("button", { name: "Delete" }));
  expect(confirm).toHaveBeenLastCalledWith("Delete this comment?");
  expect(page.state.rows).toBe(originalRows);
  fireEvent.click(screen.getByRole("button", { name: "中文" }));
  fireEvent.click(screen.getByRole("button", { name: "删除" }));
  expect(confirm).toHaveBeenLastCalledWith("删除这条评论？");
  expect(page.state.rows).toBe(originalRows);
  expect(fetchSpy).not.toHaveBeenCalled();
});

test("actual discussion loads original comments after StrictMode cleanup and remount", async () => {
  localStorage.clear();
  const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response(
    JSON.stringify(originalRows), { status: 200, headers: { "Content-Type": "application/json" } },
  ));
  render(<StrictMode><UiLocaleProvider><Discussion
    course={{ id: "original-course", visibility: "private" }}
    user={{ id: "student", name: "用户 Qwen" }} refresh={vi.fn()} toast={vi.fn()}
  /></UiLocaleProvider></StrictMode>);
  expect(await screen.findByText("用户原文讨论 DeepSeek 和 Qwen")).toBeVisible();
  expect(screen.getByText("原始回复，保持中文")).toBeVisible();
  expect(fetchSpy.mock.calls.every(([url, options]) => String(url).endsWith("/courses/original-course/comments")
    && !(options as RequestInit)?.method)).toBe(true);
});

test("the cleaned-up mount cannot replace comments delivered to the current mount", async () => {
  localStorage.clear();
  const pending: Array<(response: Response) => void> = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(() => new Promise<Response>(resolve => pending.push(resolve)));
  render(<StrictMode><UiLocaleProvider><Discussion
    course={{ id: "original-course", visibility: "private" }}
    user={{ id: "student", name: "用户 Qwen" }} refresh={vi.fn()} toast={vi.fn()}
  /></UiLocaleProvider></StrictMode>);
  // token lookup precedes fetch; settle only that local boundary.
  await act(async () => { await Promise.resolve(); });
  expect(pending).toHaveLength(2);
  await act(async () => pending[1]!(new Response(JSON.stringify(originalRows), { status: 200 })));
  expect(screen.getByText("用户原文讨论 DeepSeek 和 Qwen")).toBeVisible();
  await act(async () => pending[0]!(new Response("[]", { status: 200 })));
  expect(screen.getByText("用户原文讨论 DeepSeek 和 Qwen")).toBeVisible();
  expect(screen.queryByText("开始这门课的第一段讨论")).not.toBeInTheDocument();
});

