import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { App } from "./App.jsx";
import { UiLocaleProvider } from "./UiLocale";

test("actual shell keeps its instance and course names while translating dashboard and navigation", () => {
  const boot = vi.spyOn(App.prototype, "boot").mockImplementation(async function (this: any) {
    this.context.setOwner("student-a");
    this.setState({ loading: false, user: { id: "student-a", name: "Student", handle: "a" },
      config: { environment: "production", auth_mode: "clerk" },
      courses: [{ id: "course-a", name: "用户课程 Qwen", code: "TEST", color: "#38585b", pinned: true }],
      route: { page: "dashboard" } });
  });
  let instance: any;
  const view = render(<UiLocaleProvider><App ref={value => { instance = value; }} /></UiLocaleProvider>);
  const original = instance;
  const controls = view.container.querySelector(".dashboard-controls")!;
  const theme = controls.querySelector(".theme-toggle")!;
  const language = controls.querySelector(".cj-language-control")!;
  expect(theme.nextElementSibling).toBe(language);
  const fetchSpy = vi.spyOn(globalThis, "fetch");
  fireEvent.click(within(controls as HTMLElement).getByRole("button", { name: "English" }));
  expect(instance).toBe(original);
  expect(boot).toHaveBeenCalledTimes(1);
  expect(fetchSpy).not.toHaveBeenCalled();
  expect(screen.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  expect(screen.getByRole("navigation", { name: "Main navigation" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Import from Canvas" })).toBeVisible();
  expect(screen.getByRole("heading", { name: "用户课程 Qwen" })).toBeVisible();
  expect(instance.state.user.id).toBe("student-a");
  expect(instance.state.courses[0].id).toBe("course-a");
});
