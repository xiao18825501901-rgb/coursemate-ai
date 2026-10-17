from dataclasses import dataclass

import pytest

from app.errors import ApiError
from app.learning.assessment_point_catalog_models import (
    CatalogScope,
    VerifiedCatalog,
    VerifiedPoint,
)
from app.learning.assessment_point_configuration import AssessmentPointPolicyService


@dataclass(frozen=True)
class Source:
    owner_user_id: str = "owner-1"
    course_id: str = "course-1"
    node_id: str = "node-1"
    spec_version: int = 1

    def identity(self) -> str:
        return "a" * 64


def point(index: int) -> VerifiedPoint:
    return VerifiedPoint.model_validate(
        {
            "point_id": f"point-{index}",
            "canonical_key": f"graph.point.{index}",
            "objective": f"Demonstrate point {index}",
            "constraints": ["Use the stated course condition."],
            "scoring_evidence": ["A checkable result is produced."],
            "allowed_forms": ["SHORT_TEXT"],
            "sequence": index,
            "source_refs": [
                {
                    "source_id": f"chunk-{index}",
                    "document_id": "document-1",
                    "document_version": "version-1",
                    "locator": f"section {index}",
                    "scope_key": "owner-1:course-1:document-1",
                }
            ],
            "validation_receipt_id": f"review:{index}",
        }
    )


class Reader:
    def __init__(self, count: int) -> None:
        source = Source()
        self.catalog = VerifiedCatalog(
            catalog_id="catalog:1",
            scope=CatalogScope(
                owner_id=source.owner_user_id,
                course_id=source.course_id,
                node_id=source.node_id,
                spec_version=str(source.spec_version),
                source_snapshot=source.identity(),
            ),
            points=[point(index) for index in range(1, count + 1)],
            validation_receipt_id="review:catalog",
        )

    def read_with_targets_for(
        self, source: Source, language: str
    ) -> tuple[VerifiedCatalog, dict[str, tuple[str, ...]]]:
        assert language == "en"
        return self.catalog, {
            item.point_id: (f"objective-{item.sequence}",) for item in self.catalog.points
        }


@pytest.mark.parametrize("count", [1, 2, 3, 5])
def test_setup_derives_default_n_and_maximum_from_verified_k(count: int) -> None:
    setup = AssessmentPointPolicyService(Reader(count)).setup(Source(), "en")

    assert setup["status"] == "READY"
    assert setup["minimum_questions"] == count
    assert setup["maximum_questions"] == count * 2
    assert len(setup["default_slots"]) == count
    assert "scoring_evidence" not in str(setup)
    assert "source_refs" not in str(setup)


def test_k_two_allows_n_two_three_four_and_rejects_third_item() -> None:
    service = AssessmentPointPolicyService(Reader(2))
    setup = service.setup(Source(), "en")
    defaults = setup["default_slots"]

    for selected in (
        defaults,
        defaults
        + [
            {
                **defaults[0],
                "slot_id": "point-one-second",
                "variation_purpose": "CONDITION_CHANGE",
            }
        ],
        defaults
        + [
            {
                **defaults[0],
                "slot_id": "point-one-second",
                "variation_purpose": "CONDITION_CHANGE",
            },
            {
                **defaults[1],
                "slot_id": "point-two-second",
                "variation_purpose": "APPLICATION",
            },
        ],
    ):
        plan = service.freeze_plan(Source(), "en", f"intent-{len(selected)}", selected)
        assert len(plan.items) == len(selected)
        assert sum(item.marks_basis_points for item in plan.items) == 10_000

    third = list(defaults) + [
        {**defaults[0], "slot_id": "second", "variation_purpose": "APPLICATION"},
        {**defaults[0], "slot_id": "third", "variation_purpose": "ERROR_DIAGNOSIS"},
    ]
    with pytest.raises(ApiError) as refused:
        service.freeze_plan(Source(), "en", "intent-third", third)
    assert refused.value.code == "ASSESSMENT_POINT_ITEM_LIMIT"


def test_missing_catalog_is_not_reported_as_confirmed_zero() -> None:
    class Missing:
        def read_with_targets_for(self, source: Source, language: str) -> None:
            return None

    setup = AssessmentPointPolicyService(Missing()).setup(Source(), "en")

    assert setup["status"] == "ASSESSMENT_POINTS_NOT_READY"
    assert setup["minimum_questions"] == 0
    assert setup["maximum_questions"] == 0
    assert setup.get("confirmed_zero") is not True
