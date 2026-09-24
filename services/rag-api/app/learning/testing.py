"""Explicit synthetic fixtures; never imported by a production provider path."""

from typing import Any


def fixture_output(schema: str, context: dict[str, Any]) -> dict[str, Any]:
    if schema == "BlindSolveOutput":
        return {
            "schema_version": "blind-solve-output.v1",
            "solvability": "SOLVABLE",
            "conclusion": "[FAKE TEST FIXTURE] Synthetic independent conclusion.",
            "steps": [
                {
                    "ordinal": 1,
                    "operation": "Apply the supplied bounded rule",
                    "result": "[FAKE TEST FIXTURE] Synthetic blind-solve result",
                    "explanation": (
                        "[FAKE TEST FIXTURE] This proves the provider contract only, not "
                        "live model quality or mathematical correctness."
                    ),
                }
            ],
            "assumptions": ["Synthetic fixture, not a live independent solve"],
        }
    if schema == "QuestionAuthorOutput":
        blueprint = context["blueprint"]
        evidence_ids = context["evidence_pack"]["evidence_ids"]
        source_id = evidence_ids[0]
        is_mcq = blueprint["question_type"] == "MCQ_SINGLE"
        return {
            "schema_version": "question-author-output.v1",
            "question_text": (
                "[FAKE TEST FIXTURE] Apply the bounded course rule to the supplied "
                "synthetic example and report the result."
            ),
            "options": ["Synthetic option A", "Synthetic option B"] if is_mcq else [],
            "candidate_answer": "[FAKE TEST FIXTURE] Synthetic candidate answer.",
            "correct_option_index": 1 if is_mcq else None,
            "solution_steps": [
                {
                    "ordinal": 1,
                    "operation": "Apply the cited bounded rule",
                    "result": "[FAKE TEST FIXTURE] Synthetic result",
                    "explanation": (
                        "[FAKE TEST FIXTURE] This is a labelled contract fixture, not a live "
                        "model-quality result."
                    ),
                    "source_refs": [source_id],
                }
            ],
            "source_refs": [source_id],
        }
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
        title = (context.get("topic") or "").strip() or f"{context['course_id']} core concept"
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
            "title": title[:150],
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
    if schema == "AssessmentReferenceSolutionOutput":
        return {
            "schema_version": "v3.2",
            "answer": "[FAKE TEST FIXTURE] Reference answer.",
            "steps": [
                {
                    "step_id": "step_1",
                    "ordinal": 1,
                    "operation": "Derive the reference result",
                    "result": "[FAKE TEST FIXTURE] result",
                    "explanation": "[FAKE TEST FIXTURE] Synthetic reference step.",
                    "source_refs": [],
                }
            ],
        }
    if schema == "AssessmentExplanationOutput":
        return {"text": "[FAKE TEST FIXTURE] Synthetic step explanation."}
    if schema == "AssessmentPreparationOutput":
        def _step(operation: str, result: str, explanation: str) -> dict[str, Any]:
            return {
                "step_id": "step_1",
                "ordinal": 1,
                "operation": operation,
                "result": result,
                "explanation": explanation,
                "source_refs": [],
            }

        def _numeric(family: str, prompt: str, value: int) -> dict[str, Any]:
            return {
                "family_id": family,
                "question_type": "NUMERIC",
                "difficulty": 1,
                "prompt": prompt,
                "options": [],
                "answer": {"value": value, "tolerance": 0},
                "reference_answer": f"The result is {value}.",
                "reference_steps": [_step("Compute", str(value), f"Result is {value}.")],
                "criteria": [
                    {
                        "criterion_id": "correctness",
                        "dimension": "CALCULATION",
                        "max_fraction": 100,
                        "description": "Produces the correct result.",
                    }
                ],
            }

        return {
            "schema_version": "v3.2",
            "questions": [
                _numeric("family_prep_1", "Calculate 2 + 2.", 4),
                {
                    "family_id": "family_prep_2",
                    "question_type": "MCQ_SINGLE",
                    "difficulty": 2,
                    "prompt": "Choose 1 + 1.",
                    "options": ["1", "2", "3"],
                    "answer": {"correct_option": "1"},
                    "reference_answer": "The correct option is 2.",
                    "reference_steps": [_step("Choose", "2", "1 + 1 = 2.")],
                    "criteria": [
                        {
                            "criterion_id": "correctness",
                            "dimension": "CALCULATION",
                            "max_fraction": 100,
                            "description": "Produces the correct result.",
                        }
                    ],
                },
                _numeric("family_prep_3", "Calculate 5 - 3.", 2),
                {
                    "family_id": "family_prep_4",
                    "question_type": "SHORT_TEXT",
                    "difficulty": 1,
                    "prompt": "Write two in words.",
                    "options": [],
                    "answer": {"accepted": ["two"], "case_sensitive": False},
                    "reference_answer": "two",
                    "reference_steps": [_step("Write", "two", "The word is two.")],
                    "criteria": [
                        {
                            "criterion_id": "correctness",
                            "dimension": "CALCULATION",
                            "max_fraction": 100,
                            "description": "Produces the correct result.",
                        }
                    ],
                },
                {
                    "family_id": "family_prep_5",
                    "question_type": "EXPLANATION",
                    "difficulty": 3,
                    "prompt": "Explain why addition combines counts.",
                    "options": [],
                    "answer": {
                        "reference_answer": "Addition combines the sizes of disjoint groups."
                    },
                    "reference_answer": "Addition combines the sizes of disjoint groups.",
                    "reference_steps": [
                        _step(
                            "Explain",
                            "Disjoint groups combine",
                            "Addition sums disjoint counts.",
                        )
                    ],
                    "criteria": [
                        {
                            "criterion_id": "concept",
                            "dimension": "CONCEPT",
                            "max_fraction": 60,
                            "description": "States the combining concept.",
                        },
                        {
                            "criterion_id": "clarity",
                            "dimension": "CLARITY",
                            "max_fraction": 40,
                            "description": "Clear expression.",
                        },
                    ],
                },
            ],
        }
    raise ValueError("Unsupported synthetic fixture schema")
