import hashlib
import json
from typing import Any

import pytest
from pydantic import SecretStr
from test_assessment_point_sources import seeded
from test_learning_workspace import client_at

from app.errors import ApiError
from app.learning.assessment_point_sources import freeze_point_sources, verify_point_sources
from app.learning.generic_provider import build_generic_provider
from app.learning.provider import LearningProvider, ProviderCallFailure
from app.learning.structured_calls import GenericStructuredCalls, ModelCallClaim


def canonical_hash(value: dict[str, Any]) -> str:
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()


class ControlledGate:
    def __init__(self):
        self.qualified = True

    def require(self, source, language, method_identity):
        if not self.qualified:
            raise ApiError(409, "POINT_METHOD_NOT_QUALIFIED", "Not qualified.")
        return {
            "qualification_id": "TEST_ONLY-method",
            "cases": ["support", "scorable", "coverage", "dedup", "conditions"],
            "method_identity": method_identity,
            "model": "qwen3.8-max",
            "content_language": language,
            "source_snapshot": source.identity(),
            "test_only": True,
        }


class ControlledTransport:
    def __init__(self, source):
        self.source = source
        self.roles = []
        self.unknown_role = None
        self.compiled = None

    def candidate(self):
        target = self.source.targets[0]
        fragment = target.fragments[0]
        return {
            "points": [
                {
                    "point_id": "point-1",
                    "canonical_key": "point.one",
                    "objective": target.objective_text,
                    "constraints": [fragment.content],
                    "scoring_evidence": [target.acceptance],
                    "source_refs": [
                        {
                            "source_id": fragment.evidence_id,
                            "document_id": fragment.document_id,
                            "document_version": fragment.document_version_id,
                            "locator": fragment.locator,
                        }
                    ],
                    "allowed_forms": ["SHORT_TEXT"],
                    "sequence": 0,
                    "target_item_ids": [target.objective_id],
                }
            ]
        }

    def review(self):
        target = self.source.targets[0]
        fragment = target.fragments[0]
        point = self.compiled["points"][0]
        return {
            "source_snapshot": self.source.identity(),
            "candidate_hash": canonical_hash(self.compiled),
            "points": [
                {
                    "point_id": point["point_id"],
                    "canonical_key": point["canonical_key"],
                    "target_item_ids": point["target_item_ids"],
                    "supported": True,
                    "observable": True,
                    "scorable": True,
                    "conditions_preserved": True,
                    "reason": "TEST_ONLY exact source and scoring evidence checked.",
                    "evidence_quotes": [
                        {"source_id": fragment.evidence_id, "quote": fragment.content}
                    ],
                }
            ],
            "covered_target_item_ids": [target.objective_id],
            "deduplicated": True,
        }

    def generate(self, provider: LearningProvider, schema, **kwargs):
        role = kwargs["role"]
        sink = kwargs["transport_event_sink"]
        sink({"phase": "SEND_INTENT"})
        self.roles.append(role)
        run = {"status": "COMPLETED", "provider_response_id": "TEST_ONLY-response"}
        if self.unknown_role == role:
            run["status"] = "UNKNOWN"
            raise ProviderCallFailure(TimeoutError("TEST_ONLY timeout"), run)
        payload = self.candidate() if role == "ASSESSABLE_POINT_COMPILE" else self.review()
        output = schema.model_validate(payload)
        if role == "ASSESSABLE_POINT_COMPILE":
            self.compiled = output.model_dump(mode="json")
        sink(
            {
                "phase": "RESPONSE_COMPLETE",
                "returned_model": "qwen3.8-max",
                "reasoning_effort_requested": "xhigh",
                "native_reasoning_observed": True,
                "usage_reported": True,
                "input_tokens": 11,
                "output_tokens": 7,
                "provider_response_id": "TEST_ONLY-response",
            }
        )
        return output, run


@pytest.fixture
def case(tmp_path, monkeypatch):
    with client_at(tmp_path) as client:
        workspace, node, _, _ = seeded(client)
        database = client.app.state.database
        source = freeze_point_sources(
            database,
            workspace_id=workspace["id"],
            owner="a",
            node_id=node["id"],
        )
        settings = client.app.state.settings.model_copy(
            update={
                "generic_llm_enabled": True,
                "cj_qwen_api_key": SecretStr("TEST_ONLY-placeholder"),
                "cj_qwen_capability_receipt_id": "TEST_ONLY-capability",
                "cj_qwen_secret_generation_id": "TEST_ONLY-generation",
            }
        )
        transport = ControlledTransport(source)
        monkeypatch.setattr(
            LearningProvider,
            "generate",
            lambda provider, schema, **kwargs: transport.generate(
                provider, schema, **kwargs
            ),
        )
        calls = GenericStructuredCalls(database, settings, build_generic_provider(settings))
        claim = ModelCallClaim(
            "TEST_ONLY-prepare",
            "a",
            source.course_id,
            "en",
            lambda: verify_point_sources(database, source),
        )
        yield database, calls, source, claim, ControlledGate(), transport


def service(case):
    from app.learning.assessment_point_catalog import AssessmentPointCatalogService

    database, calls, _, _, gate, _ = case
    return AssessmentPointCatalogService(database, calls, gate)


def test_unqualified_method_refuses_before_any_send(case):
    _, _, source, claim, gate, transport = case
    gate.qualified = False
    with pytest.raises(ApiError) as caught:
        service(case).prepare_for(claim, source)
    assert caught.value.code == "POINT_METHOD_NOT_QUALIFIED"
    assert transport.roles == []


def test_compile_and_review_publish_then_reuse_verified_catalog(case):
    _, _, source, claim, _, transport = case
    subject = service(case)
    first = subject.prepare_for(claim, source)
    second = subject.prepare_for(claim, source)

    assert first == second == subject.read_for(source, "en")
    assert first.version == "cj.assessment.points.v1"
    assert len(first.points) == 1
    assert first.points[0].status == "VERIFIED"
    assert transport.roles == ["ASSESSABLE_POINT_COMPILE", "LLM_REVIEW"]


@pytest.mark.parametrize("unknown_role", ["ASSESSABLE_POINT_COMPILE", "LLM_REVIEW"])
def test_unknown_stage_cannot_publish_or_be_resent(case, unknown_role):
    _, _, source, claim, _, transport = case
    transport.unknown_role = unknown_role
    subject = service(case)
    for _ in range(2):
        with pytest.raises((ApiError, TimeoutError)):
            subject.prepare_for(claim, source)
        assert subject.read_for(source, "en") is None
    assert transport.roles.count(unknown_role) == 1
