import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

const api = vi.hoisted(() => ({
  request: vi.fn(),
  getVisualAssistance: vi.fn(),
  listPairs: vi.fn(),
}));

vi.mock("./api.js", async () => {
  const actual = await vi.importActual<typeof import("./api.js")>("./api.js");
  return {
    ...actual,
    request: api.request,
    getVisualAssistance: api.getVisualAssistance,
    listPairs: api.listPairs,
  };
});

import { Learn } from "./pages.jsx";
import { UiLocaleProvider } from "./UiLocale";

beforeEach(() => {
  localStorage.clear();
  api.request.mockReset();
  api.getVisualAssistance.mockReset();
  api.listPairs.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

test("a throttled knowledge index does not disable visual consent or text learning", async () => {
  api.request.mockImplementation((path: string) => {
    if (path === "/courses/course-1/knowledge") {
      return Promise.reject(new Error("请求失败（429）"));
    }
    if (path === "/courses/course-1/layout") {
      return Promise.resolve({ ratio: 0.5, active_node: null });
    }
    if (path === "/courses/course-1/knowledge-build-status") {
      return Promise.resolve({ status: "EMPTY" });
    }
    return Promise.reject(new Error(`unexpected request: ${path}`));
  });
  api.getVisualAssistance.mockResolvedValue({
    enabled: false,
    video_enabled: true,
    consent_version: "visual-assistance-v1",
  });
  api.listPairs.mockResolvedValue([]);

  render(
    <UiLocaleProvider>
      <Learn
        course={{ id: "course-1", code: "BIO101", name: "Biology" }}
        user={{ id: "user-1", name: "Student" }}
        config={{
          provider_mode: "configured",
          visual_engine_enabled: true,
          visual_auto_enabled: false,
        }}
        toast={vi.fn()}
        modal={vi.fn()}
        closeModal={vi.fn()}
      />
    </UiLocaleProvider>,
  );

  await waitFor(() => {
    expect(
      screen.getByRole("button", { name: /图片\/视频辅助/ }),
    ).toBeEnabled();
  });
  expect(screen.getByText("请求失败（429）")).toBeVisible();
  expect(screen.getByRole("heading", { name: "知识学习" })).toBeVisible();
});
