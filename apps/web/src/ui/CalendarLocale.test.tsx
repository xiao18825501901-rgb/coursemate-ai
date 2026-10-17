import { act, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import type { ReactNode } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { Calendar } from "./pages.jsx";
import { App } from "./App.jsx";
import { LanguageControl, UiLocaleProvider } from "./UiLocale";

afterEach(() => vi.restoreAllMocks());
const originalTask = { id: "original-task", version: 7, title: "用户 Qwen 学习安排",
  status: "todo", due_at: "2026-10-05T06:00:00Z", course: "original-course" };
const courses = [{ id: "original-course", code: "ORIG", name: "用户 DeepSeek 课程" }];

function mounted() {
  localStorage.clear();
  vi.spyOn(Calendar.prototype, "load").mockImplementation(async function (this: any) {
    this.setState({ tasks: [originalTask], month: new Date(2026, 9, 1) });
  });
  let page: any;
  const opened = vi.fn();
  function Shell() {
    const [body, setBody] = useState<ReactNode>(null);
    return <><LanguageControl /><Calendar ref={value => { page = value; }}
      courses={courses} user={{ id: "student", timezone: "Asia/Shanghai" }}
      modal={(title: any, next: ReactNode) => { opened(title); setBody(next); }}
      closeModal={vi.fn()} toast={vi.fn()} />{body}</>;
  }
  render(<UiLocaleProvider><Shell /></UiLocaleProvider>);
  return { get page() { return page; }, opened };
}

test("calendar translates controls without changing tasks, version, month or plan/model content", () => {
  const { page } = mounted();
  fireEvent.change(screen.getByRole("textbox", { name: "自然语言学习安排" }),
    { target: { value: "我的中文 Qwen 计划草稿" } });
  act(() => page.setState({ answer: "原始模型回复，保持中文 DeepSeek" }));
  const state = page.state;
  const fetch = vi.spyOn(globalThis, "fetch");
  fireEvent.click(screen.getByRole("button", { name: "English" }));
  expect(screen.getByRole("heading", { name: "Calendar" })).toBeVisible();
  expect(screen.getByRole("heading", { name: "October 2026" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Previous month" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Next month" })).toBeVisible();
  expect(screen.getByRole("textbox", { name: "Natural-language study plan" })).toHaveValue(
    "我的中文 Qwen 计划草稿");
  expect(screen.getByText("原始模型回复，保持中文 DeepSeek")).toBeVisible();
  expect(screen.getByRole("button", { name: "Complete 用户 Qwen 学习安排" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Edit 用户 Qwen 学习安排" })).toBeVisible();
  expect(page.state).toBe(state);
  expect(page.state.tasks[0]).toBe(originalTask);
  expect(page.state.tasks[0].version).toBe(7);
  fireEvent.click(screen.getByRole("button", { name: "中文" }));
  expect(screen.getByRole("textbox", { name: "自然语言学习安排" })).toHaveValue(
    "我的中文 Qwen 计划草稿");
  expect(page.state).toBe(state);
  expect(fetch).not.toHaveBeenCalled();
});

test("calendar keyboard date entry and live task form locale preserve uncontrolled input values", () => {
  const { page, opened } = mounted();
  const day = screen.getByRole("button", { name: "2026-10-06 添加安排" });
  day.focus();
  fireEvent.keyDown(day, { key: " " });
  expect(opened).toHaveBeenCalledTimes(1);
  expect(opened).toHaveBeenLastCalledWith({ titleKey: "calendar.createTask" });
  const title = screen.getByRole("textbox", { name: "学习内容" });
  fireEvent.change(title, { target: { value: "未提交的中文计划" } });
  const date = screen.getByLabelText("日期") as HTMLInputElement;
  const time = screen.getByLabelText("时间") as HTMLInputElement;
  fireEvent.change(date, { target: { value: "2026-10-07" } });
  fireEvent.change(time, { target: { value: "16:35" } });
  fireEvent.change(screen.getByRole("combobox", { name: "所属课程" }),
    { target: { value: "original-course" } });
  const state = page.state;
  const fetch = vi.spyOn(globalThis, "fetch");
  fireEvent.click(screen.getByRole("button", { name: "English" }));
  expect(screen.getByRole("textbox", { name: "Study content" })).toBe(title);
  expect(title).toHaveValue("未提交的中文计划");
  expect(screen.getByLabelText("Date")).toBe(date);
  expect(date).toHaveValue("2026-10-07");
  expect(screen.getByLabelText("Time")).toBe(time);
  expect(time).toHaveValue("16:35");
  expect(screen.getByRole("combobox", { name: "Related course" })).toHaveValue("original-course");
  expect(screen.getByRole("option", { name: "ORIG 用户 DeepSeek 课程" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Save task" })).toBeVisible();
  expect(page.state).toBe(state);
  expect(fetch).not.toHaveBeenCalled();
});

test("actual shell modal title and aria locale change without remounting task draft", () => {
  localStorage.clear();
  vi.spyOn(Calendar.prototype, "load").mockImplementation(async function (this: any) {
    this.setState({ tasks: [originalTask] });
  });
  vi.spyOn(App.prototype, "boot").mockImplementation(async function (this: any) {
    this.setState({ loading: false, user: { id: "student", name: "用户", timezone: "Asia/Shanghai" },
      config: { environment: "production", auth_mode: "clerk" }, courses,
      route: { page: "calendar" } });
  });
  render(<UiLocaleProvider><LanguageControl /><App /></UiLocaleProvider>);
  fireEvent.click(screen.getByRole("button", { name: "新建安排" }));
  expect(screen.getByRole("dialog", { name: "新建学习安排" })).toBeVisible();
  const draft = screen.getByRole("textbox", { name: "学习内容" });
  fireEvent.change(draft, { target: { value: "实际弹窗草稿，语言不重置" } });
  const fetch = vi.spyOn(globalThis, "fetch");
  fireEvent.click(screen.getByRole("button", { name: "English" }));
  expect(screen.getByRole("dialog", { name: "Create study task" })).toBeVisible();
  expect(screen.getByRole("textbox", { name: "Study content" })).toBe(draft);
  expect(draft).toHaveValue("实际弹窗草稿，语言不重置");
  expect(screen.getByRole("button", { name: "Close window" })).toBeVisible();
  expect(fetch).not.toHaveBeenCalled();
});

