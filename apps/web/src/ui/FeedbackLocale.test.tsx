import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { FeedbackForm } from "./pages.jsx";
import { LanguageControl, UiLocaleProvider } from "./UiLocale";

beforeEach(() => localStorage.clear());
afterEach(() => vi.restoreAllMocks());

test("issue report form translates without losing the category, consent, or draft", () => {
  let instance: any;
  const fetchSpy = vi.spyOn(globalThis, "fetch");
  render(<UiLocaleProvider><LanguageControl/><FeedbackForm
    ref={value => { instance = value; }}
    course={{ id: "TEST_ONLY-course" }} config={{ model: "internal-audit-only" }}
    lastMessage={{ id: "TEST_ONLY-message", text: "原始题目正文" }}
    lastAnswer={{ id: "TEST_ONLY-answer", text: "原始答案正文" }}
    runId="TEST_ONLY-run" onDone={vi.fn()}
  /></UiLocaleProvider>);

  fireEvent.change(screen.getByRole("combobox"), { target: { value: "GRADING_DISPUTE" } });
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "保留问题说明草稿" } });
  fireEvent.click(screen.getByRole("button", { name: "English" }));

  expect(screen.getByText("Report one specific issue to help us improve. By default, only report identifiers and the selected category are sent.")).toBeVisible();
  expect(screen.getByText("Issue type (optional)")).toBeVisible();
  expect(screen.getByRole("combobox")).toHaveValue("GRADING_DISPUTE");
  expect(screen.getByRole("checkbox")).toBeChecked();
  expect(screen.getByRole("textbox")).toHaveValue("保留问题说明草稿");
  expect(screen.getByRole("button", { name: "Submit report" })).toBeVisible();
  expect(instance.state.category).toBe("GRADING_DISPUTE");
  expect(fetchSpy).not.toHaveBeenCalled();
});

