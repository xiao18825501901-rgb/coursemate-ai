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
    items: list[TeachingItem] = Field(max_length=30)

    @model_validator(mode="after")
    def unique_scope(self) -> "NodeDraft":
        ids = [i.item_id for i in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Teaching item IDs must be unique")
        if self.kind == "ATOMIC" and (
            not self.items or not any(i.requirement == "REQUIRED" for i in self.items)
        ):
            raise ValueError("An ATOMIC node requires at least one REQUIRED teaching item")
        if self.kind == "COMPOSITE" and self.items:
            raise ValueError(
                "A COMPOSITE node aggregates descendants and cannot own teaching items"
            )
        return self


class CheckQuestion(Contract):
    check_id: Identifier
    kind: Literal["DEFINITION", "DISTINCTION", "ENGLISH", "APPLICATION", "SYNTHESIS"]
    prompt: Text


class TeachingPlanUnit(Contract):
    unit_key: Identifier
    target_item_ids: list[Identifier] = Field(min_length=1, max_length=3)
    unit_goal: Text
    teaching_sequence: list[Text] = Field(min_length=1, max_length=8)
    adaptation: str = Field(max_length=2000)
    selected_evidence_ids: list[Identifier] = Field(max_length=20)
    suggested_exercise_blueprint: str = Field(max_length=2000)
    check_questions: list[CheckQuestion] = Field(min_length=3, max_length=5)
    instruction_draft: str = Field(max_length=3000)
    stop_condition: Literal["UNIT_COMPLETE", "MISSING_EVIDENCE"]

    @model_validator(mode="after")
    def unique_unit_scope(self) -> "TeachingPlanUnit":
        if len(self.target_item_ids) != len(set(self.target_item_ids)):
            raise ValueError("Teaching plan unit item IDs must be unique")
        check_ids = [question.check_id for question in self.check_questions]
        if len(check_ids) != len(set(check_ids)):
            raise ValueError("Teaching plan check IDs must be unique within a unit")
        return self


class TeachingPlan(Contract):
    schema_version: Literal["v3.2"]
    case_type: Literal["CASE_A", "CASE_B"]
    node_id: Identifier
    spec_version: int = Field(ge=1)
    preference_interpretation: str = Field(max_length=2000)
    units: list[TeachingPlanUnit] = Field(min_length=1, max_length=12)
    problem_bridge_id: Identifier | None
    uncertainties: list[Text] = Field(max_length=10)

    @model_validator(mode="after")
    def unique_plan_scope(self) -> "TeachingPlan":
        unit_keys = [unit.unit_key for unit in self.units]
        item_ids = [item_id for unit in self.units for item_id in unit.target_item_ids]
        if len(unit_keys) != len(set(unit_keys)):
            raise ValueError("Teaching plan unit keys must be unique")
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("A Teaching Item may be scheduled only once per plan")
        return self


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


class StepKnowledgeLink(Contract):
    resolution_status: Literal["VALIDATED", "UNRESOLVED"]
    node_id: Identifier | None = None
    spec_version: int | None = Field(default=None, ge=1)
    item_id: Identifier | None = None
    question_text: Text
    reason: Text
    unresolved_reason: Text | None = None

    @model_validator(mode="after")
    def complete_or_explicitly_unresolved(self) -> "StepKnowledgeLink":
        identity = (self.node_id, self.spec_version, self.item_id)
        if self.resolution_status == "VALIDATED":
            if any(value is None for value in identity) or self.unresolved_reason is not None:
                raise ValueError("A validated StepKnowledgeLink needs an exact Spec item")
        elif any(value is not None for value in identity) or self.unresolved_reason is None:
            raise ValueError("An unresolved StepKnowledgeLink cannot invent a node binding")
        return self


class TeachingUnitOutput(Contract):
    plan_unit_key: Identifier
    completion_status: Literal["COMPLETED", "INCOMPLETE"]
    sections: list[Section] = Field(min_length=1, max_length=8)
    terms: list[Text] = Field(max_length=20)
    formulas_examples: list[Text] = Field(max_length=10)
    source_refs: list[Identifier] = Field(max_length=20)
    coverage_proposals: list[CoverageProposal] = Field(max_length=3)
    comprehension_checks: list[CheckQuestion] = Field(min_length=3, max_length=5)
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
    formulae: list[Text] = Field(default_factory=list, max_length=10)
    units: list[Text] = Field(default_factory=list, max_length=10)
    check: Text | None = None
    knowledge_links: list[StepKnowledgeLink] = Field(min_length=1, max_length=5)
    source_refs: list[Identifier] = Field(max_length=10)

    @model_validator(mode="after")
    def unique_validated_nodes(self) -> "SolutionStep":
        node_ids = [
            link.node_id
            for link in self.knowledge_links
            if link.resolution_status == "VALIDATED"
        ]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("A solution step may ask only one question per bound node")
        return self


class ProblemSolutionOutput(Contract):
    # Only an independently checked derivation/pairing may upgrade this in the backend.
    answer_origin: Literal["MODEL_PROPOSED"]
    exam_answer: Text
    conditions: list[Text] = Field(max_length=20)
    steps: list[SolutionStep] = Field(min_length=1, max_length=12)
    assumptions: list[Text] = Field(max_length=10)
    common_mistakes: list[Text] = Field(default_factory=list, max_length=10)
    question_transcription: Text | None = None
    visual_uncertainties: list[Text] = Field(default_factory=list, max_length=20)
    verification: Literal["NOT_INDEPENDENTLY_VERIFIED"]


class OperationInput(Contract):
    operation_id: Identifier
    revision: int = Field(ge=0)


class SolveInput(OperationInput):
    question: Text | None = None
    node_ids: list[Identifier] = Field(min_length=1, max_length=10)
    scope: Literal["official", "mine", "union"] = "union"
    problem_index_entry_id: Identifier | None = None
    image_document_version_id: Identifier | None = None
    transcription_hint: Text | None = None

    @model_validator(mode="after")
    def one_problem_source(self) -> "SolveInput":
        if self.problem_index_entry_id and self.image_document_version_id:
            raise ValueError("Choose either an indexed question or one image")
        if self.problem_index_entry_id and self.question is not None:
            raise ValueError("An indexed question must use its saved version text")
        if not (self.question or self.problem_index_entry_id or self.image_document_version_id):
            raise ValueError("Provide question text, an indexed question, or an image")
        if self.transcription_hint is not None and self.image_document_version_id is None:
            raise ValueError("A transcription hint belongs to an image question")
        return self


class BridgeInput(OperationInput):
    step_id: Identifier
    knowledge_link_id: Identifier | None = None
    node_id: Identifier | None = None

    @model_validator(mode="after")
    def link_or_legacy_node(self) -> "BridgeInput":
        if self.knowledge_link_id is None and self.node_id is None:
            raise ValueError("Select a saved StepKnowledgeLink")
        return self


class TeachInput(OperationInput):
    node_id: Identifier
    bridge_id: Identifier | None = None
    preference: str = Field(default="", max_length=2000)
    language: Literal["zh-CN", "en", "bilingual"] = "zh-CN"
    replan: bool = False


class Layout(Contract):
    orientation: Literal["columns", "rows"] = "columns"
    swapped: bool = False
    ratio: int = Field(default=50, ge=30, le=70)


class PreferenceInput(OperationInput):
    mode: Literal["AUTO", "TEACHING", "PROBLEM"]
    layout: Layout


class ReturnInput(OperationInput):
    status: Literal["COMPLETED", "CANCELLED"] = "COMPLETED"


class TreeMembershipInput(Contract):
    node_id: Identifier
    parent_node_id: Identifier | None = None
    ordinal: int = Field(ge=0, le=10_000)
    spec_version: int | None = Field(default=None, ge=1)


class PrerequisiteInput(Contract):
    node_id: Identifier
    prerequisite_node_id: Identifier


class PersonalPlanInput(OperationInput):
    title: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]
    change_reason: Text
    memberships: list[TreeMembershipInput] = Field(min_length=1, max_length=500)
    prerequisites: list[PrerequisiteInput] = Field(default_factory=list, max_length=1_000)

    @model_validator(mode="after")
    def unique_graph_entries(self) -> "PersonalPlanInput":
        nodes = [member.node_id for member in self.memberships]
        edges = [
            (edge.node_id, edge.prerequisite_node_id) for edge in self.prerequisites
        ]
        if len(nodes) != len(set(nodes)):
            raise ValueError("Each knowledge node may appear only once in a tree version")
        if len(edges) != len(set(edges)):
            raise ValueError("Prerequisite edges must be unique")
        return self


class TeachingSpecDraft(OperationInput):
    change_reason: Text
    items: list[TeachingItem] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def valid_items(self) -> "TeachingSpecDraft":
        ids = [item.item_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Teaching item IDs must be unique")
        if not any(item.requirement == "REQUIRED" for item in self.items):
            raise ValueError("A specification requires at least one REQUIRED item")
        return self
