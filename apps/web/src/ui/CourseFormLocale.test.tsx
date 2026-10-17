import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { App } from "./App.jsx";
import { UiLocaleProvider } from "./UiLocale";

beforeEach(() => localStorage.clear());

function mount() {
  vi.spyOn(App.prototype, "boot").mockImplementation(async function (this: any) {
    this.context.setOwner("course-form-owner");
    this.setState({ loading: false, user: { id: "course-form-owner", name: "Student", handle: "a" },
      config: { environment: "production", auth_mode: "clerk" }, courses: [],
      route: { page: "dashboard" } });
  });
  let instance: any;
  const view = render(<UiLocaleProvider><App ref={value => { instance = value; }} /></UiLocaleProvider>);
  return { view, instance };
}

test("create-course dialog follows UI locale without remounting drafts, files or color", () => {
  const { instance } = mount();
  fireEvent.click(screen.getByRole("button", { name: "创建自己的课程" }));
  const form = screen.getByRole("dialog").querySelector("form")!;
  const name = form.querySelector('[name="name"]') as HTMLInputElement;
  const requirements = form.querySelector('[name="requirements"]') as HTMLTextAreaElement;
  fireEvent.change(name, { target: { value: "原课 Qwen 生物医学" } });
  fireEvent.change(requirements, { target: { value: "中文教学，保留英文术语；Do not translate me." } });
  fireEvent.click(within(form).getByRole("button", { name: "课程颜色 #756480" }));
  const file = new File(["原始资料 Qwen"], "资料-DeepSeek.txt", { type: "text/plain" });
  fireEvent.change(form.querySelector('input[type="file"]')!, { target: { files: [file] } });
  const fetchSpy = vi.spyOn(globalThis, "fetch");
  act(() => instance.context.setLocale("en"));
  const dialog = screen.getByRole("dialog", { name: "Create your course" });
  expect(dialog.querySelector("form")).toBe(form);
  expect(screen.getByLabelText("Course name")).toBe(name);
  expect(screen.getByLabelText("How would you like to learn?")).toBe(requirements);
  expect(name.value).toBe("原课 Qwen 生物医学");
  expect(requirements.value).toBe("中文教学，保留英文术语；Do not translate me.");
  expect(within(dialog).getByText("资料-DeepSeek.txt")).toBeVisible();
  expect(within(dialog).getByRole("button", { name: "Course color #756480" })).toHaveClass("selected");
  expect(within(dialog).getByRole("button", { name: "Create course and upload 1 file" })).toBeEnabled();
  expect(fetchSpy).not.toHaveBeenCalled();
  act(() => instance.context.setLocale("zh-CN"));
  expect(screen.getByRole("dialog", { name: "创建你的课程" }).querySelector("form")).toBe(form);
  expect(name.value).toBe("原课 Qwen 生物医学");
  expect(requirements.value).toContain("中文教学");
});

