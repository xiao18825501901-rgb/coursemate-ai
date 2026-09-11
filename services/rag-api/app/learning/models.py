from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=6000)]
Identifier = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9_-]{1,100}$")]
Major = Literal["CS", "SMART_MANUFACTURING", "MATERIALS", "ENERGY"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TeachingItem(Contract):
    item_id: Identifier
    requirement: Literal["REQUIRED", "RECOMMENDED", "OPTIONAL"]
    objective: Text
    acceptance: Text
    evidence_ids: list[Identifier] = Field(max_length=20)


class NodeDraft(Contract):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
    description: Text
    major: Major
    kind: Literal["ATOMIC", "COMPOSITE"] = "ATOMIC"
    items: list[TeachingItem] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def unique_scope(self) -> "NodeDraft":
        ids = [i.item_id for i in self.items]
        if len(ids) != len(set(ids)) or not any(i.requirement == "REQUIRED" for i in self.items):
            raise ValueError("Unique item IDs and at least one REQUIRED item are necessary")
        return self


class TeachingPlan(Contract):
    case: Literal["CASE_A", "CASE_B"]
    node_id: Identifier
    spec_version: int = Field(ge=1)
    target_item_ids: list[Identifier] = Field(min_length=1, max_length=3)
    unit_goal: Text
    teaching_sequence: list[Text] = Field(min_length=1, max_length=8)
    adaptation: str = Field(max_length=2000)
    selected_evidence_ids: list[Identifier] = Field(max_length=20)
    problem_bridge_id: Identifier | None
    suggested_exercise_blueprint: str = Field(max_length=2000)
    remaining_scope_plan: list[Text] = Field(max_length=30)
    uncertainties: list[Text] = Field(max_length=10)
    stop_condition: Literal["UNIT_COMPLETE", "MISSING_EVIDENCE"]


class Section(Contract):
    section_id: Identifier
    title: Text
    content: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=40, max_length=12000)
    ]


class CoverageProposal(Contract):
    item_id: Identifier
    section_ids: list[Identifier] = Field(min_length=1, max_length=8)


class KnowledgeLink(Contract):
    node_id: Identifier
    question_text: Text
    reason: Text


class TeachingUnitOutput(Contract):
    sections: list[Section] = Field(min_length=1, max_length=8)
    terms: list[Text] = Field(max_length=20)
    formulas_examples: list[Text] = Field(max_length=10)
    source_refs: list[Identifier] = Field(max_length=20)
    coverage_proposals: list[CoverageProposal] = Field(max_length=3)
    knowledge_questions: list[KnowledgeLink] = Field(max_length=10)
    return_anchor: str | None = Field(max_length=200)
    next_actions: list[Literal["CONTINUE", "EXAMPLE", "RETURN", "ASSESS", "PAUSE"]] = Field(
        max_length=5
    )
    uncertainties: list[Text] = Field(max_length=10)


class SolutionStep(Contract):
    operation: Text
    result: Text
    explanation: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=20, max_length=6000)
    ]
    knowledge_links: list[KnowledgeLink] = Field(min_length=1, max_length=5)
    source_refs: list[Identifier] = Field(max_length=10)


class ProblemSolutionOutput(Contract):
    # Only an independently checked derivation/pairing may upgrade this in the backend.
    answer_origin: Literal["MODEL_PROPOSED"]
    exam_answer: Text
    conditions: list[Text] = Field(max_length=20)
    steps: list[SolutionStep] = Field(min_length=1, max_length=12)
    assumptions: list[Text] = Field(max_length=10)
    verification: Literal["NOT_INDEPENDENTLY_VERIFIED"]


class OperationInput(Contract):
    operation_id: Identifier
    revision: int = Field(ge=0)


class SolveInput(OperationInput):
    question: Text
    node_ids: list[Identifier] = Field(min_length=1, max_length=10)
    scope: Literal["official", "mine", "union"] = "union"


class BridgeInput(OperationInput):
    step_id: Identifier
    node_id: Identifier


class TeachInput(OperationInput):
    node_id: Identifier
    bridge_id: Identifier | None = None
    preference: str = Field(default="", max_length=2000)
    language: Literal["zh-CN", "en", "bilingual"] = "zh-CN"


class Layout(Contract):
    orientation: Literal["columns", "rows"] = "columns"
    swapped: bool = False
    ratio: int = Field(default=50, ge=30, le=70)


class PreferenceInput(OperationInput):
    mode: Literal["AUTO", "TEACHING", "PROBLEM"]
    layout: Layout


class ReturnInput(OperationInput):
    status: Literal["COMPLETED", "CANCELLED"] = "COMPLETED"
