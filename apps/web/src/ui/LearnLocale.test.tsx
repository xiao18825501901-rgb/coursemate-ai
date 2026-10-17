import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { Learn } from "./pages.jsx";
import { LanguageControl, UiLocaleProvider } from "./UiLocale";

beforeEach(() => localStorage.clear());
afterEach(() => vi.restoreAllMocks());

test("learning workspace translates its primary controls without changing learning state", () => {
  vi.spyOn(Learn.prototype, "componentDidMount").mockImplementation(function (this: any) {
    this.setState({
      nodes: [{ id: "TEST_ONLY-node", title: "用户知识点 Qwen", parent: null, progress: "LEARNING" }],
      inputs: { teach: "保留未发送教学草稿", problem: "Keep unsent problem draft" },
      run: { teach: "TEST_ONLY-teach-run", problem: null },
      pair: "TEST_ONLY-pair",
      activeNode: "TEST_ONLY-node",
      thinking: { teach: true },
      status: { teach: "正在输出中", problem: "" },
    });
  });
  let instance: any;
  render(<UiLocaleProvider><LanguageControl/><Learn
    ref={value => { instance = value; }}
    course={{ id: "TEST_ONLY-course", code: "GE2324", name: "用户课程 DeepSeek" }}
    user={{ id: "TEST_ONLY-user", name: "Student" }}
    config={{ provider_mode: "qwen", visual_engine_enabled: false }}
    toast={vi.fn()} modal={vi.fn()} closeModal={vi.fn()}
  /></UiLocaleProvider>);

  const teachDraft = screen.getByDisplayValue("保留未发送教学草稿");
  const problemDraft = screen.getByDisplayValue("Keep unsent problem draft");
  const fetchSpy = vi.spyOn(globalThis, "fetch");
  fireEvent.click(screen.getByRole("button", { name: "English" }));

  expect(screen.getByText("Course knowledge")).toBeVisible();
  expect(screen.getAllByText("Knowledge learning").length).toBeGreaterThanOrEqual(2);
  expect(screen.getAllByText("Problem solving").length).toBeGreaterThanOrEqual(2);
  expect(screen.getByRole("button", { name: "Try a question" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Enable or disable lesson planning" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByText("Generating")).toBeVisible();
  act(() => instance.setLaneUiStatus("teach", "questionGenerating"));
  expect(screen.getByText("Generating a question…")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "中文" }));
  expect(screen.getByText("正在出题…")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "English" }));
  expect(teachDraft).toHaveValue("保留未发送教学草稿");
  expect(problemDraft).toHaveValue("Keep unsent problem draft");
  expect(instance.state.pair).toBe("TEST_ONLY-pair");
  expect(instance.state.run.teach).toBe("TEST_ONLY-teach-run");
  expect(instance.state.activeNode).toBe("TEST_ONLY-node");
  expect(fetchSpy).not.toHaveBeenCalled();

  act(() => instance.setState({ expanded: true, hover: "TEST_ONLY-node" }));
  expect(screen.getAllByText("用户知识点 Qwen").length).toBeGreaterThanOrEqual(2);
  expect(screen.getByText("In progress")).toBeVisible();
  expect(screen.getByText("Assessment result")).toBeVisible();
  expect(screen.getByText("Not assessed")).toBeVisible();
  expect(screen.getByText("Start assessment")).toBeVisible();
});

test("course-knowledge preparation states use the active interface language", () => {
  vi.spyOn(Learn.prototype, "componentDidMount").mockImplementation(function (this: any) {
    this.setState({ nodes: [], knowledgeBuild: { status: "QUEUED" } });
  });
  const fetchSpy = vi.spyOn(globalThis, "fetch");
  render(<UiLocaleProvider><LanguageControl/><Learn
    course={{ id: "TEST_ONLY-course", code: "GE2324", name: "用户课程" }}
    user={{ id: "TEST_ONLY-user", name: "Student" }}
    config={{ provider_mode: "configured", visual_engine_enabled: false }}
    toast={vi.fn()} modal={vi.fn()} closeModal={vi.fn()}
  /></UiLocaleProvider>);

  fireEvent.click(screen.getByRole("button", { name: "English" }));
  fireEvent.click(screen.getByText("Course knowledge"));
  expect(screen.getByRole("heading", { name: "Sources received" })).toBeVisible();
  expect(screen.getByText("The current source batch is being consolidated before course knowledge is organized.")).toBeVisible();
  expect(fetchSpy).not.toHaveBeenCalled();
});

test("practice and diagnostic chrome translates without rewriting generated content", () => {
  vi.spyOn(Learn.prototype, "componentDidMount").mockImplementation(function (this: any) {
    this.setState({
      messages: { teach: [], problem: [{
        id: "TEST_ONLY-message", role: "assistant", text: "用户生成的练习题干", exercise: "TEST_ONLY-exercise",
        exercise_state: {
          revealed: false,
          learning_cycle_id: "TEST_ONLY-cycle",
          latest_hint: { hint: "用户相关提示内容", strategy: "用户相关提示策略" },
          evidence_card: {
            label_zh: "用户原始学习证据标签",
            attempts: [],
            currently_valid_closure: false,
            historical_closure_exists: false,
            diagnostic: { status: "NOT_STARTED" },
          },
        },
      }] },
    });
  });
  render(<UiLocaleProvider><LanguageControl/><Learn
    course={{ id: "TEST_ONLY-course", code: "GE2324", name: "用户课程" }}
    user={{ id: "TEST_ONLY-user", name: "Student" }}
    config={{ provider_mode: "configured", visual_engine_enabled: false }}
    toast={vi.fn()} modal={vi.fn()} closeModal={vi.fn()}
  /></UiLocaleProvider>);

  fireEvent.click(screen.getByRole("button", { name: "English" }));
  expect(screen.getByRole("region", { name: "Optional three-question diagnostic" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Start diagnostic" })).toBeVisible();
  expect(screen.getByText("Hint")).toBeVisible();
  expect(screen.getByLabelText("Practice answer")).toHaveAttribute("placeholder", "Write your reasoning, steps, or conclusion before submitting for targeted feedback…");
  expect(screen.getByRole("button", { name: "Submit answer" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Give me a hint" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Show answer" })).toBeVisible();
  expect(screen.getByText("用户生成的练习题干")).toBeVisible();
  expect(screen.getByText("用户相关提示内容")).toBeVisible();
  expect(screen.getByText("用户原始学习证据标签")).toBeVisible();
});

test("composite assessment picker translates while preserving source titles", () => {
  let instance: any;
  vi.spyOn(Learn.prototype, "componentDidMount").mockImplementation(function (this: any) {
    instance = this;
  });
  render(<UiLocaleProvider><LanguageControl/><Learn
    course={{ id: "TEST_ONLY-course", code: "GE2324", name: "用户课程" }}
    user={{ id: "TEST_ONLY-user", name: "Student" }}
    config={{ provider_mode: "configured", visual_engine_enabled: false }}
    toast={vi.fn()} modal={vi.fn()} closeModal={vi.fn()}
  /></UiLocaleProvider>);
  act(() => instance.setState({ assessPicker: {
    parent: { id: "TEST_ONLY-parent", title: "用户综合知识点" },
    children: [{ id: "TEST_ONLY-child", title: "用户原子知识点", assessment_display: null }],
    mode: "new",
  } }));
  fireEvent.click(screen.getByRole("button", { name: "English" }));

  expect(screen.getByRole("heading", { name: "Choose a learning unit to assess" })).toBeVisible();
  expect(screen.getByText("用户综合知识点 · Composite units are not assessed directly")).toBeVisible();
  expect(screen.getByRole("button", { name: /用户原子知识点/ })).toHaveTextContent("Not assessed");
  expect(screen.getByRole("button", { name: "Cancel" })).toBeVisible();
});

