import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { PairHistory } from "./pages.jsx";
import { LanguageControl, UiLocaleProvider } from "./UiLocale";

beforeEach(() => localStorage.clear());
afterEach(() => vi.restoreAllMocks());

test("Pair history translates its chrome while preserving original records and IDs", () => {
  vi.spyOn(PairHistory.prototype, "componentDidMount").mockImplementation(function (this: any) {
    this.setState({
      rows: [{
        id: "TEST_ONLY-pair",
        title: "用户对话 Qwen",
        updated_at: "2026-10-08T00:00:00Z",
        bound_node: "TEST_ONLY-node",
        teach_conversation: "TEST_ONLY-teach",
        problem_conversation: "TEST_ONLY-problem",
      }],
      nodes: [{ id: "TEST_ONLY-node", title: "用户知识点 DeepSeek" }],
      menu: "TEST_ONLY-pair",
      legacy: [{ id: "TEST_ONLY-legacy", title: "原始测评记录", updated_at: "2026-10-07T00:00:00Z", message_count: 1 }],
      legacyOpen: {
        title: "原始测评记录",
        messages: [{ role: "user", text: "保留历史正文", citations: [{ document_id: "TEST_ONLY-document" }, {}] }],
      },
    });
  });
  let instance: any;
  const fetchSpy = vi.spyOn(globalThis, "fetch");
  render(<UiLocaleProvider><LanguageControl/><PairHistory
    ref={value => { instance = value; }}
    course="TEST_ONLY-course"
    toast={vi.fn()} closeModal={vi.fn()} onSelect={vi.fn()} onDeleted={vi.fn()}
  /></UiLocaleProvider>);

  fireEvent.click(screen.getByRole("button", { name: "English" }));
  expect(screen.getByText("用户对话 Qwen")).toBeVisible();
  expect(screen.getByText("Bound to learning unit")).toBeVisible();
  expect(screen.getByRole("button", { name: "Delete conversation 用户对话 Qwen" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Conversation actions 用户对话 Qwen" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Rename" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Change binding" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Unbind" })).toBeVisible();
  expect(screen.getByRole("heading", { name: "Earlier Q&A records" })).toBeVisible();
  expect(screen.getByText("These original Q&A records remain read-only and are not copied into Pair history.")).toBeVisible();
  expect(screen.getAllByText("原始测评记录").length).toBeGreaterThanOrEqual(2);
  expect(screen.getByText("保留历史正文")).toBeVisible();
  expect(screen.getByText("TEST_ONLY-document")).toBeVisible();
  expect(screen.getByText("Course materials")).toBeVisible();
  expect(fetchSpy).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole("button", { name: "Change binding" }));
  expect(screen.getByRole("heading", { name: "Change bound learning unit" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Back" })).toBeVisible();
  expect(screen.getByRole("textbox", { name: "Search learning units" })).toBeVisible();
  expect(screen.getByText("用户知识点 DeepSeek")).toBeVisible();
  expect(instance.state.picker.pairId).toBe("TEST_ONLY-pair");
  expect(instance.state.rows[0].teach_conversation).toBe("TEST_ONLY-teach");
});

