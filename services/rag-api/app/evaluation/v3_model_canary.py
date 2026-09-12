from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel

from app.evaluation.model_benchmark import conservative_input_token_ceiling
from app.learning.compiler import (
    TEMPLATE_VERSION,
    compile_unit,
    problem_template,
    template,
    validate_plan,
    validate_unit,
)
from app.learning.course_policy import course_policy
from app.learning.models import (
    CheckQuestion,
    Major,
    ProblemSolutionOutput,
    TeachingItem,
    TeachingPlan,
    TeachingPlanUnit,
    TeachingUnitOutput,
)
from app.learning.provider import LearningProvider, ProviderImage

Language = Literal["zh-CN", "en", "bilingual"]
CaseType = Literal["CASE_A", "CASE_B"]
CallObserver = Callable[[str, BaseModel, dict[str, Any]], None]
PROTOCOL_OVERHEAD_TOKENS = 512
IMAGE_SOURCE_VERSION_ID = "synthetic_image_canary_v1"


@dataclass(frozen=True, slots=True)
class V3TeachingCanaryCase:
    id: str
    case_type: CaseType
    major: Major
    language: Language
    preference: str
    node_id: str
    node_title: str
    node_description: str
    item: TeachingItem
    evidence_id: str
    evidence_text: str
    expected_signals: tuple[str, ...]

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> V3TeachingCanaryCase:
        preference = str(value["preference"])
        case_type = cast(CaseType, str(value["case_type"]))
        expected_case = "CASE_B" if preference.strip() else "CASE_A"
        if case_type not in {"CASE_A", "CASE_B"} or case_type != expected_case:
            raise ValueError("Canary case_type must match the presence of a preference.")
        major = str(value["major"])
        if major not in {"CS", "SMART_MANUFACTURING", "MATERIALS", "ENERGY"}:
            raise ValueError("Unsupported V3 canary major.")
        language = str(value["language"])
        if language not in {"zh-CN", "en", "bilingual"}:
            raise ValueError("Unsupported V3 canary language.")
        item = TeachingItem.model_validate(value["item"])
        evidence_id = str(value["evidence_id"])
        if evidence_id not in item.evidence_ids:
            raise ValueError("The canary evidence must be authorized by its Teaching Item.")
        expected_signals = tuple(str(signal) for signal in value["expected_signals"])
        if not expected_signals:
            raise ValueError("A canary requires human-review domain signals.")
        return cls(
            id=str(value["id"]),
            case_type=case_type,
            major=cast(Major, major),
            language=cast(Language, language),
            preference=preference,
            node_id=str(value["node_id"]),
            node_title=str(value["node_title"]),
            node_description=str(value["node_description"]),
            item=item,
            evidence_id=evidence_id,
            evidence_text=str(value["evidence_text"]),
            expected_signals=expected_signals,
        )


def load_v3_teaching_cases(path: Path) -> list[V3TeachingCanaryCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("V3 teaching canary dataset must be a JSON array.")
    cases = [V3TeachingCanaryCase.from_mapping(cast(dict[str, Any], item)) for item in payload]
    identifiers = [case.id for case in cases]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("V3 teaching canary case IDs must be unique.")
    expected_pairs = {
        (major, case_type)
        for major in ("CS", "SMART_MANUFACTURING", "MATERIALS", "ENERGY")
        for case_type in ("CASE_A", "CASE_B")
    }
    if {(case.major, case.case_type) for case in cases} != expected_pairs:
        raise ValueError(
            "V3 teaching canary dataset must contain each major and case exactly once."
        )
    if {case.language for case in cases} != {"zh-CN", "en", "bilingual"}:
        raise ValueError("V3 teaching canary dataset must cover zh-CN, en and bilingual.")
    return cases


def evidence_for(case: V3TeachingCanaryCase) -> dict[str, Any]:
    digest = hashlib.sha256(case.evidence_text.encode()).hexdigest()
    return {
        "id": case.evidence_id,
        "document_id": f"{case.evidence_id}_document",
        "document_version_id": f"{case.evidence_id}_document_v1",
        "document_version": digest,
        "locator_type": "benchmark_case",
        "locator_value": case.id,
        "content": case.evidence_text,
        "scope": "benchmark",
        "source_scope": "BENCHMARK_SYNTHETIC",
    }


def node_for(case: V3TeachingCanaryCase) -> dict[str, Any]:
    spec_content = json.dumps([case.item.model_dump()], ensure_ascii=False, sort_keys=True)
    return {
        "id": case.node_id,
        "course_id": "synthetic-v3-canary",
        "title": case.node_title,
        "description": case.node_description,
        "major": case.major,
        "kind": "ATOMIC",
        "status": "PRIVATE",
        "created_at": "1970-01-01T00:00:00Z",
        "spec_version": 1,
        "spec_hash": hashlib.sha256(spec_content.encode()).hexdigest(),
        "items": [case.item.model_dump()],
    }


def planner_context(
    case: V3TeachingCanaryCase,
    *,
    output_budget: int = 4_000,
) -> dict[str, Any]:
    evidence = evidence_for(case)
    return {
        "node_id": case.node_id,
        "knowledge_node": node_for(case),
        "teaching_spec_version": 1,
        "spec_version": 1,
        "required_items": [case.item.model_dump()],
        "recommended_items": [],
        "optional_items": [],
        "eligible": [case.item.model_dump()],
        "covered_item_ids": [],
        "performance_replan_triggers": [],
        "planning_scope": "UNCOVERED_REQUIRED",
        "preference": case.preference,
        "language": case.language,
        "major_policy": case.major,
        "course_policy": course_policy("synthetic-v3-canary").model_dump(),
        "learning_cursor": {},
        "evidence": [evidence],
        "bridge_id": None,
        "bridge": None,
        "output_budget": output_budget,
    }


def run_teaching_case(
    case: V3TeachingCanaryCase,
    provider: LearningProvider,
    *,
    on_call: CallObserver | None = None,
) -> dict[str, Any]:
    context = planner_context(
        case,
        output_budget=provider.settings.v3_max_output_tokens,
    )
    plan, planner_run = provider.generate(
        TeachingPlan,
        instructions=template("planner"),
        context=context,
        role="planner",
        template_version=TEMPLATE_VERSION,
        schema_version="v3.2",
    )
    if on_call is not None:
        on_call("planner", plan, planner_run)
    validate_plan(
        plan,
        node_id=case.node_id,
        spec_version=1,
        eligible=[case.item],
        evidence_ids=[case.evidence_id],
        bridge_id=None,
        expected_case=case.case_type,
    )
    unit_plan = plan.units[0]
    if unit_plan.stop_condition != "UNIT_COMPLETE":
        raise ValueError(
            "The live canary cannot complete because the plan reports missing evidence."
        )
    selected = [evidence_for(case)] if case.evidence_id in unit_plan.selected_evidence_ids else []
    unit_context = {**context, "evidence": selected}
    instructions, compiled = compile_unit(
        major=case.major,
        plan=plan,
        unit_plan=unit_plan,
        items=[case.item],
        context=unit_context,
    )
    unit, teacher_run = provider.generate(
        TeachingUnitOutput,
        instructions=instructions,
        context={
            "compiled": json.loads(compiled),
            "plan": plan.model_dump(),
            "plan_unit": unit_plan.model_dump(),
            "return_anchor": None,
        },
        role="teacher",
        template_version=TEMPLATE_VERSION,
        schema_version="v3.2",
    )
    if on_call is not None:
        on_call("teacher", unit, teacher_run)
    validate_unit(
        unit,
        plan=plan,
        unit_plan=unit_plan,
        node_ids={case.node_id},
        return_anchor=None,
    )
    checks = {
        "case_type": plan.case_type == case.case_type,
        "required_scope": {
            item_id for planned_unit in plan.units for item_id in planned_unit.target_item_ids
        }
        == {case.item.item_id},
        "unit_completed": unit.completion_status == "COMPLETED",
        "coverage_exact": {proposal.item_id for proposal in unit.coverage_proposals}
        == {case.item.item_id},
        "checks_bounded": 3 <= len(unit.comprehension_checks) <= 5,
        "source_scope": set(unit.source_refs) <= set(unit_plan.selected_evidence_ids),
        "provider_runs_completed": planner_run["status"] == teacher_run["status"] == "COMPLETED",
    }
    return {
        "case_id": case.id,
        "major": case.major,
        "case_type": case.case_type,
        "language": case.language,
        "expected_signals_for_human_review": list(case.expected_signals),
        "automated_pass": all(checks.values()),
        "checks": checks,
        "plan": plan.model_dump(),
        "unit": unit.model_dump(),
        "runs": [planner_run, teacher_run],
        "manual_review": {
            "status": "REQUIRED",
            "domain_accuracy": None,
            "teaching_depth": None,
            "grounding": None,
            "language_quality": None,
            "preference_adherence": None,
            "hallucination_or_unsafe_claims": None,
            "reviewer_notes": "",
        },
    }


def _serialized_provider_input(
    schema: type[BaseModel],
    context: dict[str, Any],
    *,
    image_content: bytes | None = None,
    image_media_type: str | None = None,
) -> str:
    images: list[dict[str, Any]] = []
    if image_content is not None and image_media_type is not None:
        images.append(
            {
                "source_version_id": IMAGE_SOURCE_VERSION_ID,
                "media_type": image_media_type,
                "sha256": hashlib.sha256(image_content).hexdigest(),
                "byte_size": len(image_content),
            }
        )
    return json.dumps(
        {
            "authorized_context": context,
            "authorized_images": images,
            "required_output_schema": schema.model_json_schema(),
        },
        ensure_ascii=False,
    )


def _representative_plan(case: V3TeachingCanaryCase) -> TeachingPlan:
    return TeachingPlan(
        schema_version="v3.2",
        case_type=case.case_type,
        node_id=case.node_id,
        spec_version=1,
        preference_interpretation=case.preference,
        units=[
            TeachingPlanUnit(
                unit_key="unit_1",
                target_item_ids=[case.item.item_id],
                unit_goal=case.item.objective,
                teaching_sequence=["intuition", "definition", "application"],
                adaptation=case.preference,
                selected_evidence_ids=[case.evidence_id],
                suggested_exercise_blueprint="One bounded synthetic check",
                check_questions=[
                    CheckQuestion(
                        check_id="definition_check",
                        kind="DEFINITION",
                        prompt="State the bounded concept.",
                    ),
                    CheckQuestion(
                        check_id="distinction_check",
                        kind="DISTINCTION",
                        prompt="Distinguish the nearest concept.",
                    ),
                    CheckQuestion(
                        check_id="application_check",
                        kind="APPLICATION",
                        prompt="Apply it to the synthetic evidence.",
                    ),
                ],
                instruction_draft="Teach only the bounded synthetic item.",
                stop_condition="UNIT_COMPLETE",
            )
        ],
        problem_bridge_id=None,
        uncertainties=[],
    )


def image_problem_context() -> dict[str, Any]:
    return {
        "input_kind": "IMAGE",
        "question": "Transcribe and solve the authorized synthetic arithmetic image.",
        "transcription_hint": None,
        "indexed_source": None,
        "image_source": {
            "document_version_id": IMAGE_SOURCE_VERSION_ID,
            "source_scope": "BENCHMARK_SYNTHETIC",
        },
        "nodes": [
            {
                "id": "canary_image_addition",
                "spec_version": 1,
                "items": [
                    {
                        "item_id": "addition_principle",
                        "requirement": "REQUIRED",
                        "objective": "Explain addition",
                        "acceptance": "Show a checkable addition step",
                        "evidence_ids": [],
                    }
                ],
            }
        ],
        "evidence": [],
    }


def run_image_problem_case(
    provider: LearningProvider,
    *,
    image_content: bytes,
    image_media_type: Literal["image/png", "image/jpeg"],
    on_call: CallObserver | None = None,
) -> dict[str, Any]:
    context = image_problem_context()
    instructions, template_version = problem_template()
    image = ProviderImage(
        media_type=image_media_type,
        content=image_content,
        sha256=hashlib.sha256(image_content).hexdigest(),
        source_version_id=IMAGE_SOURCE_VERSION_ID,
    )
    output, run = provider.generate(
        ProblemSolutionOutput,
        instructions=instructions,
        context=context,
        role="problem",
        template_version=template_version,
        schema_version="ProblemSolutionOutput:v2",
        images=[image],
    )
    if on_call is not None:
        on_call("problem", output, run)
    links = [link for step in output.steps for link in step.knowledge_links]
    checks = {
        "completed": run["status"] == "COMPLETED",
        "transcription_present": bool(output.question_transcription),
        "uncertainty_explicit": isinstance(output.visual_uncertainties, list),
        "answer_is_model_proposed": output.answer_origin == "MODEL_PROPOSED",
        "not_independently_verified": output.verification == "NOT_INDEPENDENTLY_VERIFIED",
        "step_links_present": bool(links),
        "step_links_bounded": all(
            link.resolution_status == "UNRESOLVED"
            or (
                link.node_id == "canary_image_addition"
                and link.spec_version == 1
                and link.item_id == "addition_principle"
            )
            for link in links
        ),
    }
    return {
        "case_id": "image-problem",
        "image": {
            "media_type": image_media_type,
            "sha256": image.sha256,
            "byte_size": len(image_content),
        },
        "automated_pass": all(checks.values()),
        "checks": checks,
        "output": output.model_dump(),
        "runs": [run],
        "manual_review": {
            "status": "REQUIRED",
            "transcription_accuracy": None,
            "visual_sign_and_symbol_accuracy": None,
            "solution_correctness": None,
            "uncertainty_calibration": None,
            "reviewer_notes": "",
        },
    }


def call_input_token_ceilings(
    cases: Iterable[V3TeachingCanaryCase],
    *,
    max_output_tokens: int,
    image_content: bytes,
    image_media_type: str,
) -> list[int]:
    if max_output_tokens <= 0:
        raise ValueError("max_output_tokens must be positive.")
    ceilings: list[int] = []
    for case in cases:
        context = planner_context(case, output_budget=max_output_tokens)
        planner_input = _serialized_provider_input(TeachingPlan, context)
        ceilings.append(
            conservative_input_token_ceiling(
                template("planner"),
                planner_input,
                protocol_overhead_tokens=PROTOCOL_OVERHEAD_TOKENS,
            )
        )
        plan = _representative_plan(case)
        unit_plan = plan.units[0]
        instructions, compiled = compile_unit(
            major=case.major,
            plan=plan,
            unit_plan=unit_plan,
            items=[case.item],
            context={**context, "evidence": [evidence_for(case)]},
        )
        teacher_input = _serialized_provider_input(
            TeachingUnitOutput,
            {
                "compiled": json.loads(compiled),
                "plan": plan.model_dump(),
                "plan_unit": unit_plan.model_dump(),
                "return_anchor": None,
            },
        )
        ceilings.append(
            conservative_input_token_ceiling(
                instructions,
                teacher_input,
                protocol_overhead_tokens=PROTOCOL_OVERHEAD_TOKENS + max_output_tokens,
            )
        )
    problem_instructions, _ = problem_template()
    problem_input = _serialized_provider_input(
        ProblemSolutionOutput,
        image_problem_context(),
        image_content=image_content,
        image_media_type=image_media_type,
    )
    image_data_uri_bytes = len(("data:" + image_media_type + ";base64,").encode()) + len(
        base64.b64encode(image_content)
    )
    ceilings.append(
        conservative_input_token_ceiling(
            problem_instructions,
            problem_input,
            protocol_overhead_tokens=PROTOCOL_OVERHEAD_TOKENS + image_data_uri_bytes,
        )
    )
    return ceilings


def detect_image_media_type(content: bytes) -> Literal["image/png", "image/jpeg"] | None:
    if (
        len(content) >= 45
        and content.startswith(b"\x89PNG\r\n\x1a\n")
        and content[12:16] == b"IHDR"
        and int.from_bytes(content[16:20], "big") > 0
        and int.from_bytes(content[20:24], "big") > 0
        and content.endswith(b"\x00\x00\x00\x00IEND\xaeB`\x82")
    ):
        return "image/png"
    if (
        len(content) >= 20
        and content.startswith(b"\xff\xd8\xff")
        and content.endswith(b"\xff\xd9")
    ):
        return "image/jpeg"
    return None
