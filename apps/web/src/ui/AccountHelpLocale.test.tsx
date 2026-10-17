import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { App } from "./App.jsx";
import { UiLocaleProvider } from "./UiLocale";

afterEach(() => vi.restoreAllMocks());

function mounted(verification: any = { verified: false }, required = true) {
  localStorage.clear();
  vi.spyOn(App.prototype, "boot").mockImplementation(async function (this: any) {
    this.context.setOwner("account-locale-student");
    this.setState({ loading: false, user: { id: "account-locale-student", name: "用户 Qwen 姓名", handle: "original" },
      config: { environment: "production", auth_mode: "clerk", student_verification_required_for_campus: required },
      verification, route: { page: "dashboard" }, courses: [] });
  });
  let instance: any;
  render(<UiLocaleProvider><App ref={value => { instance = value; }} /></UiLocaleProvider>);
  return instance;
}

test("account drawer translates system actions and required verification, never user identity or auth", () => {
  const app = mounted();
  const user = app.state.user, verification = app.state.verification;
  const signOut = vi.fn();
  act(() => { app.logout = signOut; });
  const fetchSpy = vi.spyOn(globalThis, "fetch");
  fireEvent.click(screen.getByRole("button", { name: "English" }));
  fireEvent.click(screen.getByRole("button", { name: "Account" }));
  const drawer = screen.getByRole("dialog", { name: "Account panel" });
  for (const name of ["Sign out", "Notifications", "Profile", "Files", "Settings"]) {
    expect(within(drawer).getByRole("button", { name })).toBeVisible();
  }
  expect(within(drawer).getByText("Student verification")).toBeVisible();
  expect(within(drawer).getByText("Not verified")).toBeVisible();
  expect(within(drawer).getByText("New accounts must complete student verification to access campus courses.")).toBeVisible();
  expect(within(drawer).getByRole("heading", { name: "用户 Qwen 姓名" })).toBeVisible();
  expect(app.state.user).toBe(user); expect(app.state.verification).toBe(verification);
  fireEvent.click(within(drawer).getByRole("button", { name: "Sign out" }));
  expect(signOut).toHaveBeenCalledOnce();
  expect(fetchSpy).not.toHaveBeenCalled();
});

test.each([["registered", "Registered record"], ["code", "Redemption code"], ["grandfathered", "Existing account"]])(
  "verified method %s switches without touching saved verification", (method, label) => {
    const saved = { verified: true, method };
    const app = mounted(saved);
    fireEvent.click(screen.getByRole("button", { name: "English" }));
    fireEvent.click(screen.getByRole("button", { name: "Account" }));
    expect(screen.getByText(`Verified (${label})`)).toBeVisible();
    fireEvent.click(within(screen.getByRole("dialog", { name: "Account panel" }))
      .getByRole("button", { name: "中文" }));
    expect(screen.getByText("学生认证")).toBeVisible();
    expect(app.state.verification).toBe(saved);
    expect(app.state.user.id).toBe("account-locale-student");
  });

test("optional verification and actual help drawer provide English system copy without model calls", () => {
  const app = mounted({ verified: false }, false);
  fireEvent.click(screen.getByRole("button", { name: "English" }));
  const fetchSpy = vi.spyOn(globalThis, "fetch");
  fireEvent.click(screen.getByRole("button", { name: "Account" }));
  expect(screen.getByText("Not required")).toBeVisible();
  expect(screen.getByText("Student verification is not required for campus access under the current policy. Sign in with a valid account to study.")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Help" }));
  const help = screen.getByRole("dialog", { name: "Help panel" });
  expect(within(help).getByRole("heading", { name: "Help" })).toBeVisible();
  expect(within(help).getByText("A clear direction for every step of learning")).toBeVisible();
  for (const title of ["Start learning", "Create your own course", "Files and course materials", "Learn knowledge and solve problems", "Question explanations", "Learning history", "Calendar and study plans", "Comments and messages"]) {
    expect(within(help).getByText(title)).toBeVisible();
  }
  expect(help.textContent).not.toMatch(/控制面板|学生认证|详解|学习历史/);
  expect(app.state.route).toEqual({ page: "dashboard" });
  expect(fetchSpy).not.toHaveBeenCalled();
});

