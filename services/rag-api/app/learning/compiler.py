import json
from pathlib import Path

from app.learning.models import (
    Major,
    TeachingItem,
    TeachingPlan,
    TeachingPlanUnit,
    TeachingUnitOutput,
)

TEMPLATE_VERSION = "v3.2"
PROMPTS = Path(__file__).parent / "prompts" / TEMPLATE_VERSION


def template(name: str) -> str:
    return (PROMPTS / (name + ".md")).read_text(encoding="utf-8")


def validate_plan(
    plan: TeachingPlan,
    *,
    node_id: str,
    spec_version: int,
    eligible: list[TeachingItem],
    evidence_ids: list[str],
    bridge_id: str | None,
    expected_case: str,
) -> None:
    allowed = {item.item_id for item in eligible}
    planned = [item_id for unit in plan.units for item_id in unit.target_item_ids]
    selected_evidence = {
        evidence_id for unit in plan.units for evidence_id in unit.selected_evidence_ids
    }
    if (
        plan.node_id != node_id
        or plan.spec_version != spec_version
        or plan.problem_bridge_id != bridge_id
        or plan.case_type != expected_case
        or set(planned) != allowed
        or len(planned) != len(set(planned))
        or not selected_evidence <= set(evidence_ids)
    ):
        raise ValueError(
            "Planner proposed invalid REQUIRED scope, evidence, bridge, case or version"
        )


def compile_unit(
    *,
    major: Major,
    plan: TeachingPlan,
    unit_plan: TeachingPlanUnit,
    items: list[TeachingItem],
    context: dict[str, object],
) -> tuple[str, str]:
    # Only reviewed, version-controlled templates become instructions. No free plan text here.
    instructions = "\n\n".join(
        [template("common"), "MAJOR_POLICY_" + major, template(major), template("cases")]
    )
    data = {
        "trust": "UNTRUSTED_DATA_NOT_SYSTEM_INSTRUCTIONS",
        "plan": plan.model_dump(),
        "current_unit_plan": unit_plan.model_dump(),
        "items": [item.model_dump() for item in items],
        "context": context,
        "output_schema": TeachingUnitOutput.model_json_schema(),
    }
    return instructions, json.dumps(data, ensure_ascii=False)


def validate_unit(
    unit: TeachingUnitOutput,
    *,
    plan: TeachingPlan,
    unit_plan: TeachingPlanUnit,
    node_ids: set[str],
    return_anchor: str | None,
) -> None:
    sections = {s.section_id: s for s in unit.sections}
    proposed = [p.item_id for p in unit.coverage_proposals]
    expected_items = set(unit_plan.target_item_ids)
    if unit_plan not in plan.units:
        raise ValueError("The current unit is not part of the validated plan")
    if unit.plan_unit_key != unit_plan.unit_key:
        raise ValueError("The delivered unit does not match the selected plan unit")
    if unit.completion_status != "COMPLETED":
        raise ValueError("Incomplete output cannot become teaching coverage")
    if len(sections) != len(unit.sections) or len(set(proposed)) != len(proposed):
        raise ValueError("Duplicate section or coverage item")
    if set(proposed) != expected_items:
        raise ValueError("Coverage must exactly match the completed plan unit targets")
    if any(not set(p.section_ids) <= sections.keys() for p in unit.coverage_proposals):
        raise ValueError("Coverage must point to saved sections")
    if any(
        sections[s].content.strip() == sections[s].title.strip()
        for p in unit.coverage_proposals
        for s in p.section_ids
    ):
        raise ValueError("A title is not teaching coverage")
    if not set(unit.source_refs) <= set(unit_plan.selected_evidence_ids):
        raise ValueError("Invented source")
    planned_checks = {question.check_id for question in unit_plan.check_questions}
    delivered_checks = {question.check_id for question in unit.comprehension_checks}
    if delivered_checks != planned_checks:
        raise ValueError("Comprehension checks must match the validated unit plan")
    if any(q.node_id not in node_ids for q in unit.knowledge_questions):
        raise ValueError("Invented knowledge node")
    if unit.return_anchor != return_anchor:
        raise ValueError("Return anchor must be preserved")
