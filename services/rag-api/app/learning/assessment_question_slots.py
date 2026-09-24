"""Server-authored targets for one five-question node assessment.

A slot says what evidence a question should collect; it is not a generated
question and never carries an answer.  The five rows deliberately remain
separate from ``AssessmentBlueprintItem``: a slot is pre-generation intent,
whereas a blueprint item is the frozen reference to a READY question revision.
"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import Field

from app.learning.models import Contract, Identifier, Text
from app.learning.question_blueprint import (
    AnswerForm,
    BloomTarget,
    DifficultyFeature,
    QuestionType,
)


class AssessmentQuestionSlot(Contract):
    schema_version: Literal["assessment-question-slot.v1"] = "assessment-question-slot.v1"
    slot_key: Identifier
    ordinal: int = Field(ge=1, le=5)
    marks: int = Field(ge=1, le=100)
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
