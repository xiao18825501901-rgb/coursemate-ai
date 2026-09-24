"""Stage 5 calls the provider through the closed, answer-free blind-solve boundary."""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.config import Settings
from app.learning.blind_solve import (
    BLIND_SOLVE_FIELDS,
    BLIND_SOLVER_PROMPT_VERSION,
    BlindSolveError,
    BlindSolveOutput,
    run_blind_solve,
)
from app.learning.provider import LearningProvider, ProviderCallFailure
from app.learning.question_author import (
    AuthoredQuestionCandidate,
    AuthorProviderRun,
    AuthorSolutionStep,
    PrivateCandidateSolution,
    PublicAuthoredQuestion,
)
from app.learning.question_evidence import EvidenceFragment, QuestionEvidencePack

REVISION = "a" * 64
PRIVATE_SENTINEL = "PRIVATE-AUTHOR-SOLUTION-MUST-NOT-LEAK"


def evidence_pack(**overrides: Any) -> QuestionEvidencePack:
    values: dict[str, Any] = {
        "course_id": "cs3481",
        "node_id": "node-dbscan",
        "spec_version": 2,
        "spec_content_hash": "b" * 64,
        "objective_id": "objective-density",
        "objective_text": "Classify density-connected points.",
        "acceptance": "The classification follows the cited course rule.",
        "evidence_ids": ["chunk-course"],
        "fragments": [
            EvidenceFragment(
                evidence_id="chunk-course",
                document_id="doc-course",
                document_version_id="doc-course-v3",
                document_version=3,
                document_sha256="c" * 64,
                filename="lecture-07.md",
                source_scope="OFFICIAL",
                ordinal=4,
                locator_type="page",
                locator_value="7",
                section="DBSCAN",
                content=(
                    "A core point has at least MinPts points in its epsilon neighbourhood."
                ),
                truncated=False,
                source_content_sha256="d" * 64,
                excerpt_sha256="d" * 64,
            )
        ],
    }
    values.update(overrides)
    return QuestionEvidencePack(**values)


def candidate() -> AuthoredQuestionCandidate:
    return AuthoredQuestionCandidate(
        blueprint_id="blueprint-density-1",
        blueprint_hash="b" * 64,
        evidence_pack_hash=evidence_pack().identity(),
        question_revision=REVISION,
        course_id="cs3481",
        node_id="node-dbscan",
        objective_id="objective-density",
        question_type="NUMERIC",
        marks=15,
        public_question=PublicAuthoredQuestion(
            question_text="Given epsilon=1.5 and MinPts=3, how many points are core?",
            options=[],
            source_refs=["chunk-course"],
            answer_policy="HIDDEN_UNTIL_REVEAL",
        ),
        private_solution=PrivateCandidateSolution(
            candidate_answer=PRIVATE_SENTINEL,
            correct_option_index=None,
            solution_steps=[
                AuthorSolutionStep(
                    ordinal=1,
                    operation="PRIVATE OPERATION",
                    result="PRIVATE RESULT",
                    explanation="PRIVATE EXPLANATION THAT MUST NEVER REACH THE BLIND SOLVER.",
                    source_refs=["chunk-course"],
                )
            ],
            source_refs=["chunk-course"],
        ),
        provider_run=AuthorProviderRun(
            model="FAKE_TEST_ONLY",
            provider="deterministic",
            protocol="fixture",
            region="LOCAL_TEST",
            role="QUESTION_AUTHOR",
            template_version="question-author.v1",
            schema_version="question-author-output.v1",
            input_hash="d" * 64,
            started_at="2026-09-25T00:00:00Z",
            finished_at="2026-09-25T00:00:00Z",
            latency_ms=1,
            input_tokens=0,
            output_tokens=0,
            provider_response_id=None,
            status="COMPLETED",
            error_class=None,
        ),
    )


def output() -> BlindSolveOutput:
    return BlindSolveOutput(
        solvability="SOLVABLE",
        conclusion="There are zero core points.",
        steps=[
            {
                "ordinal": 1,
                "operation": "Count neighbourhoods",
                "result": "No count reaches three",
                "explanation": "Each point has fewer than three neighbours including itself.",
            }
        ],
        assumptions=[],
    )


def completed_run() -> dict[str, Any]:
    return {
        "model": "FAKE_TEST_ONLY",
        "provider": "deterministic",
        "protocol": "fixture",
        "region": "LOCAL_TEST",
        "role": "QUESTION_BLIND_SOLVER",
        "template_version": BLIND_SOLVER_PROMPT_VERSION,
        "schema_version": "blind-solve-output.v1",
        "input_hash": "e" * 64,
        "started_at": "2026-09-25T00:00:00Z",
        "finished_at": "2026-09-25T00:00:00Z",
        "latency_ms": 1,
        "input_tokens": 0,
        "output_tokens": 0,
        "provider_response_id": None,
        "status": "COMPLETED",
        "error_class": None,
    }


class SpyProvider:
    cache_model = "FAKE_TEST_ONLY"
    cache_protocol = "fixture"
    cache_region = "LOCAL_TEST"
    is_deepseek = False

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def generate(self, schema: type, **kwargs: Any) -> tuple[BlindSolveOutput, dict[str, Any]]:
        self.calls.append({"schema": schema, **kwargs})
        return output(), completed_run()


def test_provider_receives_only_public_question_and_allowed_rules() -> None:
    provider = SpyProvider()

    receipt = run_blind_solve(
        provider,
        candidate=candidate(),
        evidence=evidence_pack(),
    )

    assert len(provider.calls) == 1
    call = provider.calls[0]
    assert call["schema"] is BlindSolveOutput
    assert tuple(call["context"]) == BLIND_SOLVE_FIELDS
    assert call["role"] == "QUESTION_BLIND_SOLVER"
    assert call["template_version"] == BLIND_SOLVER_PROMPT_VERSION
    serialized = json.dumps(call["context"], ensure_ascii=False)
    assert PRIVATE_SENTINEL not in serialized
    assert "PRIVATE OPERATION" not in serialized
    assert "PRIVATE RESULT" not in serialized
    assert "PRIVATE EXPLANATION" not in serialized
    assert "correct_option_index" not in serialized
    assert receipt.question_revision == REVISION
    assert receipt.status == "completed"
    assert receipt.provider_run is not None
    assert receipt.provider_run.input_hash == "e" * 64
    assert receipt.is_current_for(REVISION)
    assert "zero core points" in receipt.output


def test_non_deepseek_live_provider_is_rejected_before_call() -> None:
    class HistoricalQwenProvider(SpyProvider):
        cache_model = "qwen3.8-max"
        cache_protocol = "responses"
        cache_region = "ENDPOINT_INTL"
        is_deepseek = False

    provider = HistoricalQwenProvider()

    with pytest.raises(BlindSolveError) as refusal:
        run_blind_solve(provider, candidate=candidate(), evidence=evidence_pack())

    assert refusal.value.code == "BLIND_SOLVER_PROVIDER_BLOCKED"
    assert provider.calls == []


def test_unlabelled_provider_is_rejected_before_call() -> None:
    class UnlabelledProvider:
        def __init__(self) -> None:
            self.calls = 0

        def generate(self, *_args: Any, **_kwargs: Any) -> tuple[Any, dict[str, Any]]:
            self.calls += 1
            return output(), completed_run()

    provider = UnlabelledProvider()

    with pytest.raises(BlindSolveError) as refusal:
        run_blind_solve(provider, candidate=candidate(), evidence=evidence_pack())  # type: ignore[arg-type]

    assert refusal.value.code == "BLIND_SOLVER_PROVIDER_BLOCKED"
    assert provider.calls == 0


def test_provider_failure_is_bounded_and_does_not_echo_private_output() -> None:
    class FailingProvider(SpyProvider):
        def generate(self, *_args: Any, **_kwargs: Any) -> tuple[Any, dict[str, Any]]:
            run = completed_run()
            run.update(status="FAILED", error_class="SCHEMA_INVALID")
            raise ProviderCallFailure(ValueError(PRIVATE_SENTINEL), run)

    with pytest.raises(BlindSolveError) as refusal:
        run_blind_solve(FailingProvider(), candidate=candidate(), evidence=evidence_pack())

    assert refusal.value.code == "BLIND_SOLVER_OUTPUT_INVALID"
    assert PRIVATE_SENTINEL not in str(refusal.value)
    assert refusal.value.provider_run is not None
    assert refusal.value.provider_run["status"] == "FAILED"


def test_real_learning_provider_uses_the_labelled_offline_fixture(tmp_path: Any) -> None:
    settings = Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        app_env="test",
        rag_provider_mode="deterministic",
        ui_web_dir=tmp_path / "no-web-build",
    )

    receipt = run_blind_solve(
        LearningProvider(settings),
        candidate=candidate(),
        evidence=evidence_pack(),
    )

    assert receipt.model_version == "FAKE_TEST_ONLY"
    assert receipt.provider_run is not None
    assert receipt.provider_run.status == "COMPLETED"
    assert "FAKE TEST FIXTURE" in receipt.output


def test_mismatched_evidence_pack_is_rejected_before_provider_call() -> None:
    provider = SpyProvider()
    mismatched = evidence_pack(objective_id="other-objective")

    with pytest.raises(BlindSolveError) as refusal:
        run_blind_solve(provider, candidate=candidate(), evidence=mismatched)

    assert refusal.value.code == "BLIND_SOLVER_INPUT_MISMATCH"
    assert provider.calls == []
