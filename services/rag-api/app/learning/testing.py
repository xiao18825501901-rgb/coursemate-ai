"""Explicit synthetic fixtures; never imported by a production provider path."""

from typing import Any


def fixture_output(schema: str, context: dict[str, Any]) -> dict[str, Any]:
    if schema == "ProblemSolutionOutput":
        # Not an answerer: only a labelled, fixed synthetic integration-test question is supported.
        if context["question"].replace(" ", "").lower() not in ("whatis2+3?", "2+3"):
            raise ValueError("Fake provider supports only the synthetic 2+3 fixture")
        return {
            "answer_origin": "MODEL_PROPOSED",
            "exam_answer": "[FAKE TEST FIXTURE] 2 + 3 = 5.",
            "conditions": ["Two objects and three objects"],
            "assumptions": ["Synthetic test fixture"],
            "verification": "NOT_INDEPENDENTLY_VERIFIED",
            "steps": [
                {
                    "operation": "Combine the two counts",
                    "result": "5",
                    "explanation": (
                        "Count two objects then three more: one, two, three, four, five."
                    ),
                    "knowledge_links": [
                        {
                            "node_id": context["nodes"][0]["id"],
                            "question_text": "Why do we add these counts?",
                            "reason": "This step combines quantities.",
                        }
                    ],
                    "source_refs": [],
                }
            ],
        }
    if schema == "TeachingPlan":
        eligible = context["eligible"]
        group_size = max(1, (len(eligible) + 11) // 12)
        units: list[dict[str, Any]] = []
        for index in range(0, len(eligible), group_size):
            target_ids = [item["item_id"] for item in eligible[index : index + group_size]]
            ordinal = len(units) + 1
            units.append(
                {
                    "unit_key": f"unit_{ordinal}",
                    "target_item_ids": target_ids,
                    "unit_goal": "Explain the current bounded Teaching Items",
                    "teaching_sequence": [
                        "Why this matters",
                        "Intuition and formal concept",
                        "Checkable application",
                    ],
                    "adaptation": context["preference"],
                    "selected_evidence_ids": [],
                    "suggested_exercise_blueprint": "Use a small checkable example",
                    "check_questions": [
                        {
                            "check_id": f"u{ordinal}_definition",
                            "kind": "DEFINITION",
                            "prompt": "State the idea in your own words.",
                        },
                        {
                            "check_id": f"u{ordinal}_distinction",
                            "kind": "DISTINCTION",
                            "prompt": "Contrast it with a nearby idea.",
                        },
                        {
                            "check_id": f"u{ordinal}_application",
                            "kind": "APPLICATION",
                            "prompt": "Apply it to the bounded example.",
                        },
                    ],
                    "instruction_draft": "Teach intuition, definition, example and application.",
                    "stop_condition": "UNIT_COMPLETE",
                }
            )
        return {
            "schema_version": "v3.2",
            "case_type": "CASE_B" if context["preference"] else "CASE_A",
            "node_id": context["node_id"],
            "spec_version": context["spec_version"],
            "preference_interpretation": context["preference"],
            "units": units,
            "problem_bridge_id": context["bridge_id"],
            "uncertainties": ["Synthetic fixture, not live quality proof"],
        }
    if schema == "TeachingUnitOutput":
        unit_plan = context["plan_unit"]
        return {
            "plan_unit_key": unit_plan["unit_key"],
            "completion_status": "COMPLETED",
            "sections": [
                {
                    "section_id": "explanation",
                    "title": "Combining counts / 合并数量",
                    "content": (
                        "[FAKE TEST FIXTURE] Addition combines counts of disjoint groups. "
                        "Start with two objects, then count three more. The combined group "
                        "contains five objects. 当前题中两组数量合并，2 + 3 = 5。"
                    ),
                }
            ],
            "terms": ["Addition / 加法"],
            "formulas_examples": ["2 + 3 = 5"],
            "source_refs": [],
            "coverage_proposals": [
                {"item_id": item_id, "section_ids": ["explanation"]}
                for item_id in unit_plan["target_item_ids"]
            ],
            "comprehension_checks": unit_plan["check_questions"],
            "knowledge_questions": [],
            "return_anchor": context["return_anchor"],
            "next_actions": ["RETURN", "CONTINUE", "PAUSE"],
            "uncertainties": ["Synthetic fixture, not a real course lesson"],
        }
    raise ValueError("Unsupported synthetic fixture schema")
