"""Zero-call catalog for narrowly proved finite graph-degree targets.

The reader is intentionally incomplete: it returns no catalog unless every
original REQUIRED target is one of the independently defined targets below and
every target retains the two source rules used by the deterministic publisher.
It therefore cannot turn an unknown course into K=0 or silently drop an
unsupported target.
"""

from app.learning.assessment_point_catalog import canonical_hash
from app.learning.assessment_point_catalog_models import (
    CatalogScope,
    VerifiedCatalog,
    VerifiedPoint,
)
from app.learning.assessment_point_sources import PointSourceSnapshot
from app.learning.deterministic_graph_point_assessment import (
    DEGREE_RULE,
    HANDSHAKE_RULE,
    SUPPORTED_GRAPH_POINT_SHAPES,
)


class DeterministicGraphPointCatalogReader:
    """Project exact original targets; never compile, merge or invent them."""

    def read_with_targets_for(
        self,
        source: PointSourceSnapshot,
        language: str,
    ) -> tuple[VerifiedCatalog, dict[str, tuple[str, ...]]] | None:
        if language not in {"zh-CN", "en"} or not source.targets:
            return None
        target_ids = [target.objective_id for target in source.targets]
        if (
            len(target_ids) != len(set(target_ids))
            or any(item_id not in SUPPORTED_GRAPH_POINT_SHAPES for item_id in target_ids)
        ):
            return None
        points: list[VerifiedPoint] = []
        targets: dict[str, tuple[str, ...]] = {}
        for sequence, target in enumerate(source.targets):
            combined = "\n".join(fragment.content for fragment in target.fragments)
            if DEGREE_RULE not in combined or HANDSHAKE_RULE not in combined:
                return None
            question_type, _task_form = SUPPORTED_GRAPH_POINT_SHAPES[target.objective_id]
            point_id = "graph-point-" + canonical_hash(
                {
                    "source_snapshot": source.identity(),
                    "target": target.objective_id,
                }
            )[:32]
            receipt_id = "detgraph:" + source.identity()[:32] + f":{sequence}"
            points.append(
                VerifiedPoint.model_validate(
                    {
                        "point_id": point_id,
                        "canonical_key": target.objective_id,
                        "objective": target.objective_text,
                        "constraints": [combined],
                        "scoring_evidence": [target.acceptance],
                        "allowed_forms": [question_type],
                        "sequence": sequence,
                        "source_refs": [
                            {
                                "source_id": fragment.evidence_id,
                                "document_id": fragment.document_id,
                                "document_version": fragment.document_version_id,
                                "locator": fragment.locator,
                                "scope_key": (
                                    f"workspace:{source.workspace_id}:owner:"
                                    f"{source.owner_user_id}"
                                ),
                            }
                            for fragment in target.fragments
                        ],
                        "validation_receipt_id": receipt_id,
                    }
                )
            )
            targets[point_id] = (target.objective_id,)
        catalog_receipt = "detgraph:" + source.identity()[:32] + ":catalog"
        return (
            VerifiedCatalog(
                catalog_id="detgraph:" + source.identity()[:32],
                scope=CatalogScope(
                    owner_id=source.owner_user_id,
                    course_id=source.course_id,
                    node_id=source.node_id,
                    spec_version=str(source.spec_version),
                    source_snapshot=source.identity(),
                ),
                points=points,
                validation_receipt_id=catalog_receipt,
            ),
            targets,
        )
