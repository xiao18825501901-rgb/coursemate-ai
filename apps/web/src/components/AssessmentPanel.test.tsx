import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AssessmentSession } from "../types/learning";
import { AssessmentPanel } from "./AssessmentPanel";

const assessment: AssessmentSession = {
  id: "assessment-1",
  workspace_id: "workspace-1",
  node_id: "node-1",
  blueprint_id: "blueprint-1",
  blueprint_version: 1,
  blueprint_hash: "a".repeat(64),
  spec_version: 1,
  status: "IN_PROGRESS",
  mode: "INDEPENDENT",
  assistance_status: "UNASSISTED",
  raw_score: null,
  independent_eligible: true,
  grade: {
    mapping_status: "UNCONFIGURED",
    label: null,
    numeric_value: null,
    message: "评分映射待配置",
  },
  grade_policy: {
    id: "policy-1",
    name: "Owner draft",
    provenance: "Requirements draft; not an institutional policy",
  },
  questions: [10, 15, 20, 25, 30].map((marks, index) => ({
    id: `item-${index + 1}`,
    question_revision_id: `question-${index + 1}`,
    ordinal: index + 1,
    family_id: `family-${index + 1}`,
    marks,
    source_kind: "OFFICIAL" as const,
    verification_method: "OFFICIAL",
    question_type: "SHORT_TEXT" as const,
    difficulty: index + 1,
    prompt: `Question ${index + 1}`,
    options: [],
    attempt_status: "UNANSWERED",
    assistance: "NONE",
  })),
  performance_evidence: [],
  started_at: "2026-09-12T00:00:00Z",
  submitted_at: null,
  graded_at: null,
};

describe("AssessmentPanel", () => {
  it("starts only an atomic-node assessment", () => {
    const onStart = vi.fn();
    const view = render(
      <AssessmentPanel
        assessment={null}
        busy={false}
        nodeKind="ATOMIC"
        nodeTitle="Addition"
        onAbandon={vi.fn()}
        onAssist={vi.fn()}
        onStart={onStart}
        onSubmit={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "开始五题测评" }));
    expect(onStart).toHaveBeenCalledOnce();

    view.rerender(
      <AssessmentPanel
        assessment={null}
        busy={false}
        nodeKind="COMPOSITE"
        nodeTitle="Chapter"
        onAbandon={vi.fn()}
        onAssist={vi.fn()}
        onStart={onStart}
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "开始五题测评" })).toBeDisabled();
  });

  it("collects exactly five answers and makes answer exposure explicit", () => {
    const onAssist = vi.fn();
    const onSubmit = vi.fn();
    render(
      <AssessmentPanel
        assessment={assessment}
        busy={false}
        nodeKind="ATOMIC"
        nodeTitle="Addition"
        onAbandon={vi.fn()}
        onAssist={onAssist}
        onStart={vi.fn()}
        onSubmit={onSubmit}
      />,
    );
    expect(screen.getByText("总分 100 · 五题不等权")).toBeVisible();
    expect(screen.queryByText(/correct_option|reference_answer/)).not.toBeInTheDocument();
    const submit = screen.getByRole("button", { name: "提交测评" });
    expect(submit).toBeDisabled();
    for (let ordinal = 1; ordinal <= 5; ordinal += 1) {
      fireEvent.change(screen.getByLabelText(`回答第 ${ordinal} 题`), {
        target: { value: `answer ${ordinal}` },
      });
    }
    expect(submit).toBeEnabled();
    fireEvent.click(submit);
    expect(onSubmit).toHaveBeenCalledWith([
      { blueprint_item_id: "item-1", answer: "answer 1" },
      { blueprint_item_id: "item-2", answer: "answer 2" },
      { blueprint_item_id: "item-3", answer: "answer 3" },
      { blueprint_item_id: "item-4", answer: "answer 4" },
      { blueprint_item_id: "item-5", answer: "answer 5" },
    ]);
    fireEvent.click(
      screen.getAllByRole("button", { name: "查看答案并转为练习" })[0]!,
    );
    expect(onAssist).toHaveBeenCalledWith("item-1", "ANSWER_REVEALED");
  });

  it("labels practice evidence and unconfigured grade mapping", () => {
    render(
      <AssessmentPanel
        assessment={{
          ...assessment,
          status: "GRADED",
          mode: "PRACTICE",
          assistance_status: "ANSWER_EXPOSED",
          raw_score: 80,
          independent_eligible: false,
        }}
        busy={false}
        nodeKind="ATOMIC"
        nodeTitle="Addition"
        onAbandon={vi.fn()}
        onAssist={vi.fn()}
        onStart={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.getByText("Raw Score：80 / 100")).toBeVisible();
    expect(screen.getByText("练习记录，不作为独立测评证据")).toBeVisible();
    expect(screen.getByText("评分映射待配置")).toBeVisible();
  });
});
