"""Host-owned assessment points from the current Teaching Spec and exact sources.

This projection is the normal student-entry policy.  It does not award or
rewrite the historical point-method qualification.  The immutable Teaching
Spec objective identity is the deduplication authority and every projected
point remains bound to the exact authorized source snapshot.
"""

from typing import Protocol

from app.learning.assessment_point_catalog import canonical_hash
from app.learning.assessment_point_catalog_models import (
    CatalogScope,
    VerifiedCatalog,
    VerifiedPoint,
)
from app.learning.assessment_point_sources import PointSourceSnapshot


class SpecializedPointCatalogReader(Protocol):
    def read_with_targets_for(
        self, source: PointSourceSnapshot, language: str
    ) -> tuple[VerifiedCatalog, dict[str, tuple[str, ...]]] | None: ...


class AssessmentEntrySourceCatalogReader:
    """Prefer a bounded host proof, otherwise project exact Spec objectives.

    ``VERIFIED`` on the existing internal model means source/scope verified in
    this path; it is deliberately not a formal method-qualification decision.
    Receipt ids use the explicit ``source-bound`` namespace so audit readers do
    not confuse them with model or human review receipts.
    """

    def __init__(self, specialized: SpecializedPointCatalogReader | None = None) -> None:
        self.specialized = specialized

    def read_with_targets_for(
        self, source: PointSourceSnapshot, language: str
    ) -> tuple[VerifiedCatalog, dict[str, tuple[str, ...]]] | None:
        if language not in {"zh-CN", "en"} or not source.targets:
            return None
        if self.specialized is not None:
            result = self.specialized.read_with_targets_for(source, language)
            if result is not None:
                return result

        points: list[VerifiedPoint] = []
        targets: dict[str, tuple[str, ...]] = {}
        seen_objectives: set[str] = set()
        snapshot = source.identity()
        for target in source.targets:
            # Objective ids are immutable server-owned Teaching Spec identities.
            # Never guess semantic equivalence from text or split one objective
            # into procedural substeps merely to increase K.
            if target.objective_id in seen_objectives:
                continue
            seen_objectives.add(target.objective_id)
            point_id = "source-point-" + canonical_hash(
                {"source_snapshot": snapshot, "objective_id": target.objective_id}
            )[:32]
            receipt = f"source-bound:{snapshot[:32]}:{target.objective_id}"
            points.append(
                VerifiedPoint.model_validate(
                    {
                        "point_id": point_id,
                        "canonical_key": target.objective_id,
                        "objective": target.objective_text,
                        "constraints": [fragment.content for fragment in target.fragments],
                        "scoring_evidence": [target.acceptance],
                        # A short answer is the least assumption-heavy default.
                        # The existing configuration contract may select another
                        # supported form, but still permits at most two items.
                        "allowed_forms": [
                            "SHORT_TEXT",
                            "EXPLANATION",
                            "NUMERIC",
                            "MCQ_SINGLE",
                            "CODE",
                        ],
                        "sequence": len(points),
                        "source_refs": [
                            {
                                "source_id": fragment.evidence_id,
                                "document_id": fragment.document_id,
                                "document_version": fragment.document_version_id,
                                "locator": fragment.locator,
                                "scope_key": (
                                    f"workspace:{source.workspace_id}:owner:{source.owner_user_id}"
                                    if fragment.source_scope == "WORKSPACE_PRIVATE"
                                    else f"course:{source.course_id}"
                                ),
                            }
                            for fragment in target.fragments
                        ],
                        "validation_receipt_id": receipt,
                    }
                )
            )
            targets[point_id] = (target.objective_id,)

        if not points:
            return None
        catalog_receipt = f"source-bound:{snapshot[:32]}:catalog"
        return (
            VerifiedCatalog(
                catalog_id=f"source-catalog:{snapshot[:32]}",
                scope=CatalogScope(
                    owner_id=source.owner_user_id,
                    course_id=source.course_id,
                    node_id=source.node_id,
                    spec_version=str(source.spec_version),
                    source_snapshot=snapshot,
                ),
                points=points,
                validation_receipt_id=catalog_receipt,
            ),
            targets,
        )
