import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { App } from "./App.jsx";
import { LanguageControl, UiLocaleProvider } from "./UiLocale";

afterEach(() => vi.restoreAllMocks());

function mountedCourses() {
  localStorage.clear();
  vi.spyOn(App.prototype, "boot").mockImplementation(async function (this: any) {
    this.context.setOwner("courses-locale-student");
    this.setState({ loading: false, user: { id: "courses-locale-student", name: "Student" },
      config: { environment: "production", auth_mode: "clerk", student_verification_required_for_campus: true },
      verification: { verified: false }, route: { page: "courses" },
      courses: [
        { id: "private-a", code: "PRIV", name: "用户 Qwen 课程", description: "用户 DeepSeek 原文", display_type: "private", color: "#38585b", visibility: "private", pinned: false },
        { id: "shared-a", code: "SHARED", name: "Shared fixture", display_type: "shared", color: "#38585b", visibility: "public", pinned: true },
        { id: "campus-a", code: "CAMPUS", name: "Campus fixture", display_type: "campus", color: "#38585b", visibility: "public", pinned: false },
      ] });
  });
  let instance: any;
  const view = render(<UiLocaleProvider><LanguageControl /><App ref={value => { instance = value; }} /></UiLocaleProvider>);
  return { ...view, instance };
}

test("all-courses English translates table, actions, hints and accessible labels without touching user content", () => {
  const view = mountedCourses();
  const original = view.instance;
  const courses = original.state.courses;
  const fetchSpy = vi.spyOn(globalThis, "fetch");
  fireEvent.click(screen.getByRole("button", { name: "English" }));
  expect(screen.getByRole("heading", { name: "All courses" })).toBeVisible();
  expect(screen.getByRole("heading", { name: "Turn your study materials into a course" })).toBeVisible();
  for (const name of ["Course", "Type", "Visibility", "Dashboard"]) {
    expect(screen.getByRole("columnheader", { name })).toBeVisible();
  }
  expect(screen.getByRole("button", { name: "Create course" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Import from Canvas" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Add to dashboard PRIV" })).toHaveAttribute("title", "Add to dashboard");
  expect(screen.getByRole("button", { name: "Remove from dashboard SHARED" })).toHaveAttribute("title", "Remove from dashboard");
  expect(screen.getByText("Complete student verification first")).toHaveAttribute("title", "Student verification is required first");
  expect(screen.getByText("Only me")).toBeVisible();
  expect(screen.getAllByText("Public")).toHaveLength(2);
  expect(screen.getByText("用户 Qwen 课程")).toBeVisible();
  expect(screen.getByText("PRIV · 用户 DeepSeek 原文")).toBeVisible();
  expect(view.instance).toBe(original);
  expect(original.state.courses).toBe(courses);
  expect(original.state.route).toEqual({ page: "courses" });
  expect(fetchSpy).not.toHaveBeenCalled();
});

test("switching all courses back to Chinese preserves handlers, course IDs and unverified campus guard", () => {
  const { instance } = mountedCourses();
  const pin = vi.fn(), create = vi.fn(), canvas = vi.fn();
  act(() => { instance.togglePin = pin; instance.createCourse = create; instance.canvasImport = canvas; });
  fireEvent.click(screen.getByRole("button", { name: "English" }));
  fireEvent.click(screen.getByRole("button", { name: "Add to dashboard PRIV" }));
  expect(pin).toHaveBeenCalledWith(instance.state.courses[0]);
  fireEvent.click(screen.getByRole("button", { name: "Create course" }));
  fireEvent.click(screen.getByRole("button", { name: "Import from Canvas" }));
  expect(create).toHaveBeenCalledTimes(1);
  expect(canvas).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("button", { name: /dashboard CAMPUS/ })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "中文" }));
  expect(screen.getByRole("heading", { name: "所有课程" })).toBeVisible();
  expect(screen.getByRole("button", { name: "添加到控制面板 PRIV" })).toBeVisible();
  expect(screen.getByText("先完成学生认证")).toBeVisible();
  expect(instance.state.user.id).toBe("courses-locale-student");
  expect(pin).toHaveBeenCalledTimes(1);
});

test("English course drawer reaches all courses with unchanged pinned names and closes without a request", () => {
  const { instance } = mountedCourses();
  fireEvent.click(screen.getByRole("button", { name: "English" }));
  const fetchSpy = vi.spyOn(globalThis, "fetch");
  fireEvent.click(screen.getByRole("button", { name: "Courses" }));
  expect(screen.getByRole("dialog", { name: "Courses panel" })).toBeVisible();
  expect(screen.getByRole("button", { name: "All courses" })).toBeVisible();
  expect(screen.getByText("Added to dashboard")).toBeVisible();
  expect(screen.getByText("SHARED Shared fixture")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Close sidebar" }));
  expect(instance.state.drawer).toBeNull();
  expect(fetchSpy).not.toHaveBeenCalled();
});

