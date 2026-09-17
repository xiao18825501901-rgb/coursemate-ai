"""Explicit synthetic fixtures; never imported by a production provider path."""

from typing import Any


def fixture_output(schema: str, context: dict[str, Any]) -> dict[str, Any]:
    if schema == "AssessmentGradeProposal":
        return {
            "schema_version": "v3.2",
            "questions": [
                {
                    "blueprint_item_id": question["blueprint_item_id"],
                    "criteria": [
                        {
                            "criterion_id": criterion["criterion_id"],
                            "score_fraction": 1,
                            "answer_evidence": "submitted_answer",
                            "feedback": (
                                "[FAKE TEST FIXTURE] The synthetic explanation matches "
                                "the frozen reference criterion."
                            ),
                            "confidence": 1,
                            "needs_review": False,
                        }
                        for criterion in question["rubric"]
                    ],
                }
                for question in context["questions"]
            ],
            "uncertainties": ["Synthetic fixture, not live grading quality proof"],
        }
    if schema == "ProblemSolutionOutput":
        # Not an answerer: only a labelled, fixed synthetic integration-test question is supported.
        candidate = context.get("transcription_hint") or context["question"]
        if context.get("input_kind") != "IMAGE" and "2+3" not in candidate.replace(
            " ", ""
        ).lower():
            raise ValueError("Fake provider supports only the synthetic 2+3 fixture")
        is_image = context.get("input_kind") == "IMAGE"
        node = context["nodes"][0]
        item = next(
            item for item in node["items"] if item["requirement"] == "REQUIRED"
        )
        return {
            "answer_origin": "MODEL_PROPOSED",
            "exam_answer": "[FAKE TEST FIXTURE] 2 + 3 = 5.",
            "conditions": ["Two objects and three objects"],
            "assumptions": ["Synthetic test fixture"],
            "common_mistakes": ["[FAKE TEST FIXTURE] Counting either group twice."],
            "question_transcription": (
                "[FAKE TEST FIXTURE] What is 2 + 3?" if is_image else None
            ),
            "visual_uncertainties": (
                ["[FAKE TEST FIXTURE] Visual correctness was not evaluated."]
                if is_image
                else []
            ),
            "verification": "NOT_INDEPENDENTLY_VERIFIED",
            "steps": [
                {
                    "operation": "Combine the two counts",
                    "result": "5",
                    "explanation": (
                        "Count two objects then three more: one, two, three, four, five."
                    ),
                    "formulae": ["2 + 3 = 5"],
                    "units": ["objects"],
                    "check": "Recount the combined set to obtain five objects.",
                    "knowledge_links": [
                        {
                            "resolution_status": "VALIDATED",
                            "node_id": node["id"],
                            "spec_version": node["spec_version"],
                            "item_id": item["item_id"],
                            "question_text": "Why do we add these counts?",
                            "reason": "This step combines quantities.",
                            "unresolved_reason": None,
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
    if schema == "OfficialNodeDraftOutput":
        evidence = context.get("evidence") or []
        items = [
            {
                "item_id": "core_concept",
                "requirement": "REQUIRED",
                "objective": "Explain the core concept from the official corpus",
                "acceptance": "State the concept and give one corpus example",
                "evidence_ids": [evidence[0]["id"]] if evidence else [],
            }
        ]
        return {
            "title": f"{context['course_id']} core concept",
            "description": (
                "[FAKE TEST FIXTURE] Synthetic official node draft; not live model output."
            ),
            "major": "CS",
            "kind": "ATOMIC",
            "items": items,
        }
    if schema == "OfficialTeachingSpecDraftOutput":
        return {
            "change_reason": "M6D1 deterministic canary generation",
            "items": context["node_draft"]["items"],
        }
    if schema == "OfficialKnowledgeDraftBundleOutput":
        node_context = dict(context)
        node = fixture_output("OfficialNodeDraftOutput", node_context)
        spec = fixture_output(
            "OfficialTeachingSpecDraftOutput",
            {**context, "node_draft": {"items": node["items"]}},
        )
        return {"node": node, "spec": spec}
    raise ValueError("Unsupported synthetic fixture schema")
