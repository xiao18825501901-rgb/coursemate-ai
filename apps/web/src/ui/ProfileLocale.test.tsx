import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { App } from "./App.jsx";
import { UiLocaleProvider } from "./UiLocale";
import * as api from "./api.js";

afterEach(() => vi.restoreAllMocks());
const user = { id: "profile-locale-student", name: "用户 Qwen 姓名", handle: "original",
  bio: "用户讨论 DeepSeek 的原始简介", language: "en", timezone: "Asia/Shanghai",
  discoverable: true, reply_notify: false };

function mounted() {
  localStorage.clear();
  vi.spyOn(App.prototype, "boot").mockImplementation(async function (this: any) {
    this.context.setOwner(user.id);
    this.setState({ loading: false, user, config: { environment: "production", auth_mode: "clerk" },
      courses: [], route: { page: "dashboard" } });
  });
  let app: any;
  render(<UiLocaleProvider><App ref={value => { app = value; }} /></UiLocaleProvider>);
  act(() => app.profile());
  return app;
}

test("profile modal translates live without remounting original drafts or teaching language", () => {
  const app = mounted();
  const dialog = screen.getByRole("dialog", { name: "个人资料与偏好" });
  const name = dialog.querySelector('[name="name"]') as HTMLInputElement;
  const bio = dialog.querySelector('[name="bio"]') as HTMLTextAreaElement;
  fireEvent.change(name, { target: { value: "未提交的 Qwen 名称" } });
  fireEvent.change(bio, { target: { value: "未提交的中文 DeepSeek 简介" } });
  const saved = app.state.user;
  const fetch = vi.spyOn(globalThis, "fetch");
  fireEvent.click(screen.getByRole("button", { name: "English" }));
  expect(screen.getByRole("dialog", { name: "Profile and preferences" })).toBe(dialog);
  expect(screen.getByRole("textbox", { name: "Display name" })).toBe(name);
  expect(name).toHaveValue("未提交的 Qwen 名称");
  expect(screen.getByRole("textbox", { name: "Bio" })).toBe(bio);
  expect(bio).toHaveValue("未提交的中文 DeepSeek 简介");
  expect(screen.getByRole("combobox", { name: "Teaching language" })).toHaveValue("en");
  expect(screen.getByRole("combobox", { name: "Study calendar time zone" })).toHaveValue("Asia/Shanghai");
  expect(screen.getByRole("button", { name: "Save profile" })).toBeVisible();
  expect(app.state.user).toBe(saved);
  expect(fetch).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "中文" }));
  expect(screen.getByRole("textbox", { name: "显示名称" })).toBe(name);
  expect(screen.getByRole("combobox", { name: "教学语言" })).toHaveValue("en");
});

test("profile submission preserves exact data and does not substitute UI locale", async () => {
  mounted();
  const send = vi.spyOn(api, "send").mockResolvedValue(user);
  fireEvent.click(screen.getByRole("button", { name: "English" }));
  const submit = screen.getByRole("button", { name: "Save profile" });
  await act(async () => fireEvent.submit(submit.closest("form")!));
  expect(send).toHaveBeenCalledExactlyOnceWith("/me", {
    name: user.name, handle: user.handle, bio: user.bio, language: "en",
    timezone: "Asia/Shanghai", discoverable: true, reply_notify: false }, "PATCH");
  expect(screen.getByText("Profile saved to the server")).toBeVisible();
});

test("username pattern is valid for modern HTML v-mode validation", () => {
  mounted();
  const pattern = screen.getByRole("textbox", { name: "用户名（用来查找联系人）" }).getAttribute("pattern")!;
  const matcher = new RegExp(`^(?:${pattern})$`, "v");
  expect(matcher.test("student_name-1")).toBe(true);
  expect(matcher.test("ab")).toBe(false);
  expect(matcher.test("Student")).toBe(false);
});

test("save errors translate without exposing backend model names or losing drafts", async () => {
  mounted();
  vi.spyOn(api, "send").mockRejectedValue(new Error("TEST_ONLY Qwen DeepSeek internal error"));
  fireEvent.change(screen.getByRole("textbox", { name: "显示名称" }), { target: { value: "中文草稿 Qwen" } });
  await act(async () => fireEvent.submit(screen.getByRole("button", { name: "保存资料" }).closest("form")!));
  expect(screen.getByRole("alert")).toHaveTextContent("资料保存失败");
  fireEvent.click(screen.getByRole("button", { name: "English" }));
  expect(screen.getByRole("alert")).toHaveTextContent("Could not save your profile");
  expect(screen.getByRole("alert")).not.toHaveTextContent(/Qwen|DeepSeek/);
  expect(screen.getByRole("textbox", { name: "Display name" })).toHaveValue("中文草稿 Qwen");
  expect(screen.getByRole("button", { name: "Save profile" })).toBeEnabled();
});

