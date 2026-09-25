"""Server-authored targets for one five-question node assessment.

A slot says what evidence a question should collect; it is not a generated
question and never carries an answer.  The five rows deliberately remain
separate from ``AssessmentBlueprintItem``: a slot is pre-generation intent,
whereas a blueprint item is the frozen reference to a READY question revision.
"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import Field

from app.learning.models import AssessmentSlotSelection, Contract, Identifier, Text
from app.learning.question_blueprint import (
    AnswerForm,
    BloomTarget,
    DifficultyFeature,
    QuestionType,
)


class AssessmentQuestionSlot(Contract):
    schema_version: Literal["assessment-question-slot.v1"] = "assessment-question-slot.v1"
    slot_key: Identifier
    ordinal: int = Field(ge=1, le=30)
    marks: float = Field(ge=0.01, le=100)
    marks_basis_points: int = Field(default=0, ge=0, le=10_000)
    bloom_target: BloomTarget
    target_difficulty: int = Field(ge=1, le=5)
    difficulty_features: list[DifficultyFeature] = Field(min_length=1)
    empirical_difficulty: None = None
    question_type: QuestionType
    expected_answer_form: AnswerForm
    scoring_focus: Text
    misconception_target: Text


_DEFAULT_SLOTS: Final[tuple[AssessmentQuestionSlot, ...]] = (
    AssessmentQuestionSlot(
        slot_key="concept_recognition",
        ordinal=1,
        marks=10,
        marks_basis_points=1000,
        bloom_target="REMEMBER",
        target_difficulty=1,
        difficulty_features=["CONCEPTS", "HINTS"],
        question_type="MCQ_SINGLE",
        expected_answer_form="SINGLE_CHOICE",
        scoring_focus=(
            "Recognize the governing concept and distinguish it from a nearby "
            "distractor."
        ),
        misconception_target="Confusing the target concept with a superficially similar term.",
    ),
    AssessmentQuestionSlot(
        slot_key="concept_explanation",
        ordinal=2,
        marks=15,
        marks_basis_points=1500,
        bloom_target="UNDERSTAND",
        target_difficulty=2,
        difficulty_features=["CONCEPTS", "REPRESENTATION"],
        question_type="SHORT_TEXT",
        expected_answer_form="SHORT_ANSWER",
        scoring_focus="Explain the concept in the learner's own words using the stated conditions.",
        misconception_target="Repeating terminology without explaining the relevant relationship.",
    ),
    AssessmentQuestionSlot(
        slot_key="bounded_application",
        ordinal=3,
        marks=20,
        marks_basis_points=2000,
        bloom_target="APPLY",
        target_difficulty=3,
        difficulty_features=["STEPS", "CONCEPTS"],
        question_type="EXPLANATION",
        expected_answer_form="WORKED_STEPS",
        scoring_focus="Apply the objective to a bounded case and show the checkable method steps.",
        misconception_target="Choosing the right rule but applying its steps in the wrong order.",
    ),
    AssessmentQuestionSlot(
        slot_key="method_analysis",
        ordinal=4,
        marks=25,
        marks_basis_points=2500,
        bloom_target="ANALYZE",
        target_difficulty=4,
        difficulty_features=["CONCEPTS", "REPRESENTATION", "STEPS"],
        question_type="EXPLANATION",
        expected_answer_form="WORKED_STEPS",
        scoring_focus=(
            "Analyze a case, separate the relevant conditions, and justify the "
            "chosen method."
        ),
        misconception_target=(
            "Using an observed surface feature instead of the condition that "
            "controls the method."
        ),
    ),
    AssessmentQuestionSlot(
        slot_key="reasoned_evaluation",
        ordinal=5,
        marks=30,
        marks_basis_points=3000,
        bloom_target="EVALUATE",
        target_difficulty=5,
        difficulty_features=["CONCEPTS", "REPRESENTATION", "STEPS"],
        question_type="EXPLANATION",
        expected_answer_form="WORKED_STEPS",
        scoring_focus=(
            "Evaluate a proposed solution or conclusion and defend a corrected "
            "conclusion from evidence."
        ),
        misconception_target=(
            "Accepting a plausible conclusion without checking it against the "
            "governing conditions."
        ),
    ),
)


def default_assessment_question_slots() -> tuple[AssessmentQuestionSlot, ...]:
    """Return immutable-by-validation copies of the server-owned five-slot policy."""

    return tuple(slot.model_copy(deep=True) for slot in _DEFAULT_SLOTS)


MAX_ASSESSMENT_QUESTIONS: Final = 30
SUPPORTED_ASSESSMENT_TYPES: Final[tuple[str, ...]] = (
    "MCQ_SINGLE",
    "NUMERIC",
    "SHORT_TEXT",
    "EXPLANATION",
    "CODE",
)

_TASK_FORM_POLICY: Final = {
    "concept": ("REMEMBER", 1, ["CONCEPTS", "HINTS"], "Recognize the governing concept.",
                "Confusing the target concept with a nearby term."),
    "definition": ("UNDERSTAND", 2, ["CONCEPTS", "REPRESENTATION"],
                   "Explain the definition and its conditions.",
                   "Repeating terminology without explaining the relationship."),
    "calculation": ("APPLY", 3, ["STEPS", "CONCEPTS"],
                    "Apply the method and show checkable steps.",
                    "Using the right rule with an incorrect calculation or order."),
    "analysis": ("ANALYZE", 4, ["CONCEPTS", "REPRESENTATION", "STEPS"],
                 "Analyze the conditions and justify the chosen method.",
                 "Choosing a method from a surface feature instead of its conditions."),
    "evaluation": ("EVALUATE", 5, ["CONCEPTS", "REPRESENTATION", "STEPS"],
                   "Evaluate a proposed conclusion and defend a correction.",
                   "Accepting a plausible conclusion without checking its conditions."),
    "code": ("APPLY", 3, ["STEPS", "CONCEPTS"],
             "Apply the objective in a bounded code task.",
             "Producing code without explaining the governing method."),
}

_ANSWER_FORM: Final = {
    "MCQ_SINGLE": "SINGLE_CHOICE",
    "NUMERIC": "NUMERIC_VALUE",
    "SHORT_TEXT": "SHORT_ANSWER",
    "EXPLANATION": "WORKED_STEPS",
    "CODE": "CODE_BLOCK",
}


def assessment_marks_basis_points(question_count: int) -> tuple[int, ...]:
    """Allocate exactly 100.00 points without floating-point drift."""

    if not 5 <= question_count <= MAX_ASSESSMENT_QUESTIONS:
        raise ValueError("Assessment question count must be between 5 and 30")
    if question_count == 5:
        return (1000, 1500, 2000, 2500, 3000)
    quotient, remainder = divmod(10_000, question_count)
    return tuple(quotient + (1 if ordinal < remainder else 0) for ordinal in range(question_count))


def slots_from_selections(
    selections: list[AssessmentSlotSelection],
) -> tuple[AssessmentQuestionSlot, ...]:
    """Compile content-free UI selections into server-owned generation intents."""

    marks = assessment_marks_basis_points(len(selections))
    compiled: list[AssessmentQuestionSlot] = []
    for index, (selection, basis_points) in enumerate(zip(selections, marks, strict=True), start=1):
        bloom, difficulty, features, focus, misconception = _TASK_FORM_POLICY[selection.task_form]
        # A task form cannot silently turn an explicitly selected type into a
        # different grader contract.
        if selection.question_type == "CODE" and selection.task_form != "code":
            raise ValueError("CODE slots require the code task form")
        if selection.question_type != "CODE" and selection.task_form == "code":
            raise ValueError("The code task form requires a CODE slot")
        compiled.append(
            AssessmentQuestionSlot(
                slot_key=selection.slot_id,
                ordinal=index,
                marks=basis_points / 100,
                marks_basis_points=basis_points,
                bloom_target=bloom,
                target_difficulty=difficulty,
                difficulty_features=features,
                question_type=selection.question_type,
                expected_answer_form=_ANSWER_FORM[selection.question_type],
                scoring_focus=focus,
                misconception_target=misconception,
            )
        )
    return tuple(compiled)


def assessment_setup_contract() -> dict[str, object]:
    """Content-free setup contract safe to return before generation."""

    defaults = [
        {"slot_id": slot.slot_key, "question_type": slot.question_type, "task_form": task_form}
        for slot, task_form in zip(
            _DEFAULT_SLOTS,
            ("concept", "definition", "calculation", "analysis", "evaluation"),
            strict=True,
        )
    ]
    return {
        "schema_version": "assessment-setup.v1",
        "minimum_questions": 5,
        "maximum_questions": MAX_ASSESSMENT_QUESTIONS,
        "supported_types": [
            {"id": "MCQ_SINGLE", "label": "单项选择"},
            {"id": "NUMERIC", "label": "数值计算"},
            {"id": "SHORT_TEXT", "label": "简短回答"},
            {"id": "EXPLANATION", "label": "分析与解释"},
            {"id": "CODE", "label": "代码应用"},
        ],
        "task_forms": [
            {"id": "concept", "label": "概念识别"},
            {"id": "definition", "label": "定义与条件"},
            {"id": "calculation", "label": "计算与推导"},
            {"id": "analysis", "label": "分析与解释"},
            {"id": "evaluation", "label": "找错与评价"},
            {"id": "code", "label": "代码应用"},
        ],
        "default_slots": defaults,
    }
