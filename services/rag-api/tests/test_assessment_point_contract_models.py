from typing import Any

import pytest
from pydantic import ValidationError

from app.learning.assessment_point_catalog_models import CandidatePoint, VerifiedPoint
from app.learning.models import AssessmentStartInput, PointSlotSelection


def candidate(**changes: Any) -> dict[str, Any]:
    return {
        "point_id": "point-shortest-path",
        "canonical_key": "graph.shortest_path",
        "objective": "Find a shortest path in an unweighted graph.",
        "constraints": ["The graph is unweighted."],
        "scoring_evidence": ["The learner returns a valid minimum-edge path."],
        "allowed_forms": ["SHORT_TEXT"],
        "sequence": 0,
        "source_refs": [
            {
                "source_id": "chunk-1",
                "document_id": "document-1",
                "document_version": "version-1",
                "locator": "section 1",
            }
        ],
        "target_item_ids": ["objective-1"],
        **changes,
    }


def test_candidate_is_not_a_verified_point() -> None:
    proposed = CandidatePoint.model_validate(candidate())

    assert "validation_receipt_id" not in proposed.model_dump()
    with pytest.raises(ValidationError):
        VerifiedPoint.model_validate(candidate())


@pytest.mark.parametrize(
    ("field", "value"),
    [("status", "CANDIDATE"), ("weight", 2), ("weight_receipt_id", "client")],
)
def test_verified_point_rejects_client_forged_authority(field: str, value: Any) -> None:
    payload = candidate()
    payload.pop("target_item_ids")
    payload["source_refs"][0]["scope_key"] = "owner:course:document"
    payload.update(validation_receipt_id="review:receipt", **{field: value})

    with pytest.raises(ValidationError):
        VerifiedPoint.model_validate(payload)


@pytest.mark.parametrize("parts", [0, 2, 3, True, "1"])
def test_point_selection_allows_exactly_one_integer_scored_item(parts: Any) -> None:
    with pytest.raises(ValidationError):
        PointSlotSelection.model_validate(
            {
                "slot_id": "point-item-1",
                "primary_point_id": "point-shortest-path",
                "question_type": "SHORT_TEXT",
                "task_form": "definition",
                "independently_scored_parts": parts,
            }
        )


def test_point_selection_keeps_second_item_purpose_separate_from_authority() -> None:
    selection = PointSlotSelection.model_validate(
        {
            "slot_id": "point-item-2",
            "primary_point_id": "point-shortest-path",
            "question_type": "SHORT_TEXT",
            "task_form": "definition",
            "variation_purpose": "CONDITION_CHANGE",
            "independently_scored_parts": 1,
        }
    )

    assert selection.primary_point_id == "point-shortest-path"
    assert selection.variation_purpose == "CONDITION_CHANGE"
    assert selection.independently_scored_parts == 1


def test_dynamic_start_dto_carries_intent_language_and_one_point_item() -> None:
    request = AssessmentStartInput.model_validate(
        {
            "operation_id": "operation-one",
            "revision": 1,
            "node_id": "node-one",
            "client_intent_id": "intent-one",
            "intent_action": "CONFIGURE",
            "content_language": "en",
            "slots": [
                {
                    "slot_id": "point-item-one",
                    "primary_point_id": "point-shortest-path",
                    "question_type": "SHORT_TEXT",
                    "task_form": "definition",
                    "independently_scored_parts": 1,
                }
            ],
        }
    )

    assert request.client_intent_id == "intent-one"
    assert request.content_language == "en"
    assert len(request.slots) == 1
    assert isinstance(request.slots[0], PointSlotSelection)
