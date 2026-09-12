import { useEffect, useState } from "react";

import type {
  AssessmentAnswerDraft,
  AssessmentQuestion,
  AssessmentSession,
  KnowledgeNodeKind,
} from "../types/learning";

interface AssessmentPanelProps {
  assessment: AssessmentSession | null;
  busy: boolean;
  nodeKind: KnowledgeNodeKind | undefined;
  nodeTitle: string;
  onStart: () => Promise<void> | void;
  onSubmit: (answers: AssessmentAnswerDraft[]) => Promise<void> | void;
  onAssist: (
    blueprintItemId: string,
    action: "HINT" | "TEACHING" | "ANSWER_REVEALED",
  ) => Promise<void> | void;
  onAbandon: () => Promise<void> | void;
}

function QuestionInput({
  answer,
  disabled,
  onChange,
  question,
}: {
  answer: string;
  disabled: boolean;
  onChange: (value: string) => void;
  question: AssessmentQuestion;
}) {
  if (question.question_type === "MCQ_SINGLE") {
    return (
      <fieldset className="assessment-options">
        <legend className="sr-only">回答第 {question.ordinal} 题</legend>
        {question.options.map((option, index) => (
          <label key={`${question.id}-${index}`}>
            <input
              checked={answer === String(index)}
              disabled={disabled}
              name={`assessment-${question.id}`}
              onChange={() => onChange(String(index))}
              type="radio"
              value={index}
            />
            <span>{option}</span>
          </label>
        ))}
      </fieldset>
    );
  }
  const multiline = question.question_type === "EXPLANATION" || question.question_type === "CODE";
  if (multiline) {
    return (
      <textarea
        aria-label={`回答第 ${question.ordinal} 题`}
        disabled={disabled}
        maxLength={12_000}
        onChange={(event) => onChange(event.target.value)}
        rows={question.question_type === "CODE" ? 8 : 4}
        value={answer}
      />
    );
  }
  return (
    <input
      aria-label={`回答第 ${question.ordinal} 题`}
      disabled={disabled}
      inputMode={question.question_type === "NUMERIC" ? "decimal" : "text"}
      maxLength={12_000}
      onChange={(event) => onChange(event.target.value)}
      value={answer}
    />
  );
}

export function AssessmentPanel({
  assessment,
  busy,
  nodeKind,
  nodeTitle,
  onAbandon,
  onAssist,
  onStart,
  onSubmit,
}: AssessmentPanelProps) {
  const [answers, setAnswers] = useState<Record<string, string>>({});

  useEffect(() => {
    setAnswers({});
  }, [assessment?.id]);

  const active = assessment?.status === "IN_PROGRESS";
  const complete = assessment?.status === "GRADED";
  const allAnswered = Boolean(
    active
    && assessment.questions.length === 5
    && assessment.questions.every((question) => (answers[question.id] ?? "").trim()),
  );
  const weakCount = assessment?.performance_evidence.filter(
    (evidence) => evidence.performance_band === "WEAK",
  ).length ?? 0;

  return (
    <section className="assessment-panel" id="assessment-panel" aria-labelledby="assessment-title">
      <header>
        <div>
          <span className="eyebrow">Independent axis</span>
          <h2 id="assessment-title">知识节点测评</h2>
        </div>
        <span className="assessment-node">{nodeTitle || "尚未选择知识节点"}</span>
      </header>
      <p>固定五题、不等权、Raw Score 100。教学完成度与测评成绩互不覆盖。</p>
      {!active && !complete && assessment?.status !== "SUBMITTED" && (
        <button
          disabled={busy || nodeKind !== "ATOMIC"}
          onClick={() => void onStart()}
          type="button"
        >
          开始五题测评
        </button>
      )}
      {nodeKind === "COMPOSITE" && !assessment && (
        <p>综合节点先显示其唯一原子后代的聚合结果；请选择一个原子节点开始正式测评。</p>
      )}
      {assessment && (
        <>
          <div className="assessment-summary" role="status">
            <strong>{assessment.status}</strong>
            <span>总分 100 · 五题不等权</span>
            <span>Blueprint v{assessment.blueprint_version} · Teaching Spec v{assessment.spec_version}</span>
          </div>
          {assessment.mode === "PRACTICE" && (
            <p className="assessment-warning">练习记录，不作为独立测评证据</p>
          )}
          {active && (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                if (!allAnswered) return;
                void onSubmit(assessment.questions.map((question) => ({
                  blueprint_item_id: question.id,
                  answer: answers[question.id] ?? "",
                })));
              }}
            >
              <ol className="assessment-question-list">
                {assessment.questions.map((question) => (
                  <li key={question.id}>
                    <header>
                      <strong>第 {question.ordinal} 题 · {question.marks} 分</strong>
                      <small>{question.source_kind} · 难度 {question.difficulty}</small>
                    </header>
                    <p>{question.prompt}</p>
                    <QuestionInput
                      answer={answers[question.id] ?? ""}
                      disabled={busy}
                      onChange={(answer) => setAnswers((current) => ({
                        ...current,
                        [question.id]: answer,
                      }))}
                      question={question}
                    />
                    {question.review && (
                      <div className="assessment-review">
                        <strong>已显式查看的答案</strong>
                        <pre>{JSON.stringify(question.review.answer, null, 2)}</pre>
                      </div>
                    )}
                    <button
                      disabled={busy || question.assistance === "ANSWER_REVEALED"}
                      onClick={() => void onAssist(question.id, "ANSWER_REVEALED")}
                      type="button"
                    >
                      查看答案并转为练习
                    </button>
                  </li>
                ))}
              </ol>
              <div className="assessment-actions">
                <button disabled={busy || !allAnswered} type="submit">提交测评</button>
                <button disabled={busy} onClick={() => void onAbandon()} type="button">
                  放弃本次（不记 0 分）
                </button>
              </div>
            </form>
          )}
          {assessment.status === "SUBMITTED" && (
            <p className="assessment-warning">存在无法可靠自动判断的答案，等待人工复核；当前不写 Raw Score 或等级。</p>
          )}
          {complete && (
            <section className="assessment-result" aria-label="测评结果">
              <h3>Raw Score：{assessment.raw_score} / 100</h3>
              <p>{assessment.grade.message}</p>
              {assessment.grade.label && (
                <p>映射结果：{assessment.grade.label} · {assessment.grade.numeric_value}</p>
              )}
              <small>
                GradePolicy：{assessment.grade_policy.name} · {assessment.grade_policy.provenance}
              </small>
              {weakCount > 0 && <p>已保存 {weakCount} 条 WEAK 细粒度证据；下次主动教学可据此重规划。</p>}
              <button disabled={busy} onClick={() => void onStart()} type="button">
                开始新的五题测评
              </button>
            </section>
          )}
        </>
      )}
    </section>
  );
}
