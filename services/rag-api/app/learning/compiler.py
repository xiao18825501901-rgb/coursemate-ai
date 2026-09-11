import json
from pathlib import Path

from app.learning.models import Major, TeachingItem, TeachingPlan, TeachingUnitOutput

TEMPLATE_VERSION = "v3.1"
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
) -> None:
    allowed = {item.item_id for item in eligible}
    if (
        plan.node_id != node_id
        or plan.spec_version != spec_version
        or plan.problem_bridge_id != bridge_id
        or not set(plan.target_item_ids) <= allowed
        or len(set(plan.target_item_ids)) != len(plan.target_item_ids)
        or not set(plan.selected_evidence_ids) <= set(evidence_ids)
    ):
        raise ValueError("Planner proposed invalid scope, evidence, bridge or version")


def compile_unit(
    *, major: Major, plan: TeachingPlan, items: list[TeachingItem], context: dict[str, object]
) -> tuple[str, str]:
    # Only reviewed, version-controlled templates become instructions. No free plan text here.
    instructions = "\n\n".join(
        [template("common"), "MAJOR_POLICY_" + major, template(major), template("cases")]
    )
    data = {
        "trust": "UNTRUSTED_DATA_NOT_SYSTEM_INSTRUCTIONS",
        "plan": plan.model_dump(),
        "items": [item.model_dump() for item in items],
        "context": context,
        "output_schema": TeachingUnitOutput.model_json_schema(),
    }
    return instructions, json.dumps(data, ensure_ascii=False)


def validate_unit(
    unit: TeachingUnitOutput, *, plan: TeachingPlan, node_ids: set[str], return_anchor: str | None
) -> None:
    sections = {s.section_id: s for s in unit.sections}
    proposed = [p.item_id for p in unit.coverage_proposals]
    if len(sections) != len(unit.sections) or len(set(proposed)) != len(proposed):
        raise ValueError("Duplicate section or coverage item")
    if not set(proposed) <= set(plan.target_item_ids):
        raise ValueError("Coverage outside eligible target items")
    if any(not set(p.section_ids) <= sections.keys() for p in unit.coverage_proposals):
        raise ValueError("Coverage must point to saved sections")
    if any(
        sections[s].content.strip() == sections[s].title.strip()
        for p in unit.coverage_proposals
        for s in p.section_ids
    ):
        raise ValueError("A title is not teaching coverage")
    if not set(unit.source_refs) <= set(plan.selected_evidence_ids):
        raise ValueError("Invented source")
    if any(q.node_id not in node_ids for q in unit.knowledge_questions):
        raise ValueError("Invented knowledge node")
    if unit.return_anchor != return_anchor:
        raise ValueError("Return anchor must be preserved")
