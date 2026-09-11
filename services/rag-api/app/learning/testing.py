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
        return {
            "case": "CASE_B" if context["preference"] else "CASE_A",
            "node_id": context["node_id"],
            "spec_version": context["spec_version"],
            "target_item_ids": [context["eligible"][0]["item_id"]],
            "unit_goal": "Explain the current bounded item",
            "teaching_sequence": ["Principle then example"],
            "adaptation": context["preference"],
            "selected_evidence_ids": [],
            "problem_bridge_id": context["bridge_id"],
            "suggested_exercise_blueprint": "Combine counts",
            "remaining_scope_plan": [],
            "uncertainties": ["Synthetic fixture, not live quality proof"],
            "stop_condition": "UNIT_COMPLETE",
        }
    if schema == "TeachingUnitOutput":
        return {
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
                {"item_id": context["plan"]["target_item_ids"][0], "section_ids": ["explanation"]}
            ],
            "knowledge_questions": [],
            "return_anchor": context["return_anchor"],
            "next_actions": ["RETURN", "CONTINUE", "PAUSE"],
            "uncertainties": ["Synthetic fixture, not a real course lesson"],
        }
    raise ValueError("Unsupported synthetic fixture schema")
