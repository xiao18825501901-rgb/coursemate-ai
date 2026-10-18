import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BRAND } from "../brand";
import { App } from "./App.jsx";
import { setTokenGetter } from "./api.js";

function appFor(state: Record<string, unknown> = {}) {
  // App.jsx is intentionally plain JavaScript. Keep the test fixture flexible
  // without widening any production boundary inferred from its initial nulls.
  const app = new App({}) as any;
  app.state = {
    ...app.state,
    loading: false,
    error: "",
    config: { auth_mode: "clerk", environment: "production" },
    user: null,
    courses: [],
    route: { page: "dashboard", cid: "", tab: "" },
    ...state,
  };
  app.canvasImport = vi.fn();
  app.createCourse = vi.fn();
  return app;
}

describe("minimal signed-out entry", () => {
  afterEach(() => {
    delete window.CourseMateAuth;
    delete window.COURSEMATE_CONFIG;
    setTokenGetter(async () => null);
    vi.unstubAllGlobals();
  });

  it("shows only the brand, exact tagline, and Clerk sign-in action in its idle content", () => {
    const app = appFor({ error: "请登录" });
    const { container } = render(app.render());

    expect(screen.getByText(BRAND.name)).toBeVisible();
    expect(screen.getByText("From Confusion to Revelation")).toBeVisible();
    expect(screen.getByRole("button", { name: "登录 / 注册" })).toBeVisible();
    expect(screen.queryByText("欢迎回到学习空间")).not.toBeInTheDocument();
    expect(screen.queryByText("整理课程，学习知识，一步一步解题。")).not.toBeInTheDocument();
    expect(screen.queryByText("请登录")).not.toBeInTheDocument();
    expect(container.querySelectorAll(".login-card > :not(.error-text)")).toHaveLength(3);
  });

  it("does not call the protected /me endpoint when Clerk has no signed-in session", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/config")) {
        return new Response(JSON.stringify({ auth_mode: "clerk", environment: "production" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      throw new Error(`unexpected signed-out request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    window.COURSEMATE_CONFIG = { apiBase: "https://api.example.test/ui" };
    window.CourseMateAuth = {
      getToken: vi.fn(async () => null),
      subscribe: vi.fn(() => () => undefined),
      signIn: vi.fn(),
      signOut: vi.fn(async () => undefined),
    };
    const app = new App({}) as any;
    app.setState = (patch: Record<string, unknown>) => {
      app.state = { ...app.state, ...patch };
    };

    await app.boot();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[0]).toBe("https://api.example.test/ui/config");
    expect(app.state).toMatchObject({ loading: false, user: null, error: "" });
  });
});

describe("Canvas import actions", () => {
  it("places the three real actions in one equal dashboard group after the heading", () => {
    const app = appFor({
      user: { id: "user-1", name: "Student", handle: "student" },
      courses: [
        { id: "course-1", code: "CS3481", name: "Fundamentals of Data Science", pinned: true, color: "#38585b" },
      ],
    });
    const view = render(app.renderDashboard());
    const group = screen.getByRole("group", { name: "课程操作" });
    const heading = view.container.querySelector(".dashboard-heading");
    const grid = view.container.querySelector(".dashboard-grid");
    const buttons = within(group).getAllByRole("button");

    expect(heading?.nextElementSibling).toBe(group);
    expect(buttons.map((button) => button.textContent?.trim())).toEqual([
      "从 Canvas 导入",
      "创建自己的课程",
      "进入所有课程",
    ]);
    expect(buttons).toHaveLength(3);
    expect(group).toHaveClass("cj-dashboard-actions");
    expect(grid?.querySelector(".add-course-card")).not.toBeInTheDocument();
    expect(view.container.querySelector(".dashboard-guide")).not.toBeInTheDocument();

    fireEvent.pointerDown(buttons[0]!);
    expect(app.canvasImport).not.toHaveBeenCalled();
    fireEvent.click(buttons[0]!);
    expect(app.canvasImport).toHaveBeenCalledTimes(1);
    expect(app.createCourse).not.toHaveBeenCalled();
    fireEvent.click(buttons[1]!);
    expect(app.createCourse).toHaveBeenCalledTimes(1);
    fireEvent.click(buttons[2]!);
    expect(window.location.hash).toBe("#/courses");
  });

  it("renders Canvas import as the same primary button style as create course", () => {
    const app = appFor({ user: { id: "user-1" } });
    render(app.renderCourses());

    const create = screen.getByRole("button", { name: "创建课程" });
    const canvas = screen.getByRole("button", { name: "从 Canvas 导入" });
    expect(create).toHaveClass("btn", "primary");
    expect(canvas).toHaveClass("btn", "primary");

    fireEvent.click(canvas);
    expect(app.canvasImport).toHaveBeenCalledTimes(1);
    expect(app.createCourse).not.toHaveBeenCalled();
  });
});
