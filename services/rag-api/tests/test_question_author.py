"""Stage 4 authors one private candidate from only a blueprint and its evidence pack."""

from __future__ import annotations

from typing import Any

import pytest

from app.config import Settings
from app.learning.provider import LearningProvider, ProviderCallFailure
from app.learning.question_author import (
    QUESTION_AUTHOR_PROMPT_VERSION,
    AuthorGenerationError,
    AuthorSolutionStep,
    QuestionAuthorOutput,
    author_question,
)
from app.learning.question_blueprint import QuestionBlueprint
from app.learning.question_evidence import EvidenceFragment, QuestionEvidencePack

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def evidence_pack() -> QuestionEvidencePack:
    return QuestionEvidencePack(
        course_id="cs3481",
        node_id="node-dbscan",
        spec_version=2,
        spec_content_hash=HASH_A,
        objective_id="objective-density",
        objective_text="计算 epsilon 邻域并区分核心点、边界点与噪声点",
        acceptance="所有点的分类与步骤均可由课程定义核验",
        evidence_ids=["chunk-course"],
        fragments=[
            EvidenceFragment(
                evidence_id="chunk-course",
                document_id="doc-course",
                document_version_id="doc-course-v3",
                document_version=3,
                document_sha256=HASH_B,
                filename="lecture-07.md",
                source_scope="OFFICIAL",
                ordinal=4,
                locator_type="page",
                locator_value="7",
                section="DBSCAN",
                content="A core point has at least MinPts points in its epsilon neighbourhood.",
                truncated=False,
                source_content_sha256=HASH_C,
                excerpt_sha256=HASH_C,
            )
        ],
    )


def blueprint(**overrides: Any) -> QuestionBlueprint:
    values: dict[str, Any] = {
        "blueprint_id": "blueprint-density-1",
        "course_id": "cs3481",
        "node_id": "node-dbscan",
        "spec_version": 2,
        "spec_content_hash": HASH_A,
        "objective_id": "objective-density",
        "objective_text": "计算 epsilon 邻域并区分核心点、边界点与噪声点",
        "source_scope": evidence_pack().source_scope(),
        "bloom_target": "APPLY",
        "target_difficulty": 3,
        "difficulty_features": ["STEPS", "COMPUTATION"],
        "question_type": "NUMERIC",
        "expected_answer_form": "NUMERIC_VALUE",
        "marks": 15,
        "scoring_criteria": ["邻域计数正确", "点类型判断正确"],
        "conditions": ["epsilon = 1.5", "MinPts = 3"],
        "unit_conventions": ["Euclidean distance"],
        "question_family_id": "family-density",
        "prompt_versions": {"question_author": QUESTION_AUTHOR_PROMPT_VERSION},
        "generation_policy_version": "question-generation-policy-v1",
    }
    values.update(overrides)
    return QuestionBlueprint(**values)


def author_output(**overrides: Any) -> QuestionAuthorOutput:
    values: dict[str, Any] = {
        "question_text": (
            "Given points A(0,0), B(1,0), and C(4,0), use epsilon=1.5 and MinPts=3 "
            "(including the point itself) to determine the number of core points."
        ),
        "options": [],
        "candidate_answer": "0 core points",
        "correct_option_index": None,
        "solution_steps": [
            AuthorSolutionStep(
                ordinal=1,
                operation="Count each epsilon neighbourhood",
                result="A and B have two points; C has one",
                explanation=(
                    "Each neighbourhood includes the point itself, so none reaches MinPts=3."
                ),
                source_refs=["chunk-course"],
            )
        ],
        "source_refs": ["chunk-course"],
    }
    values.update(overrides)
    return QuestionAuthorOutput(**values)


def completed_run() -> dict[str, Any]:
    return {
        "model": "FAKE_TEST_ONLY",
        "provider": "deterministic",
        "protocol": "fixture",
        "region": "LOCAL_TEST",
        "role": "QUESTION_AUTHOR",
        "template_version": QUESTION_AUTHOR_PROMPT_VERSION,
        "schema_version": "question-author-output.v1",
        "input_hash": "d" * 64,
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
    def __init__(self, output: QuestionAuthorOutput | None = None) -> None:
        self.output = output or author_output()
        self.calls: list[dict[str, Any]] = []

    def generate(self, schema: type, **kwargs: Any) -> tuple[QuestionAuthorOutput, dict[str, Any]]:
        self.calls.append({"schema": schema, **kwargs})
        return self.output, completed_run()


def test_author_receives_only_blueprint_and_evidence_and_answer_stays_private() -> None:
    provider = SpyProvider()

    candidate = author_question(provider, blueprint=blueprint(), evidence=evidence_pack())

    assert len(provider.calls) == 1
    call = provider.calls[0]
    assert call["schema"] is QuestionAuthorOutput
    assert set(call["context"]) == {"blueprint", "evidence_pack"}
    assert call["context"]["evidence_pack"]["fragments"][0]["content"].startswith(
        "A core point"
    )
    assert call["role"] == "QUESTION_AUTHOR"
    assert call["template_version"] == QUESTION_AUTHOR_PROMPT_VERSION
    assert candidate.blueprint_hash == blueprint().identity()
    assert candidate.evidence_pack_hash == evidence_pack().identity()
    assert candidate.provider_run.input_hash == "d" * 64

    public = candidate.public_payload()
    serialized = str(public)
    assert public["question_text"] == author_output().question_text
    assert "candidate_answer" not in serialized
    assert "correct_option_index" not in serialized
    assert "solution_steps" not in serialized
    assert candidate.private_solution.candidate_answer == "0 core points"
    assert "0 core points" not in repr(candidate)
    assert "Count each epsilon neighbourhood" not in repr(candidate)


def test_mismatched_blueprint_or_prompt_version_refuses_before_provider_call() -> None:
    provider = SpyProvider()
    mismatches = (
        blueprint(course_id="other-course"),
        blueprint(node_id="other-node"),
        blueprint(spec_content_hash="e" * 64),
        blueprint(prompt_versions={}),
        blueprint(prompt_versions={"question_author": "question-author.v0"}),
    )

    for item in mismatches:
        with pytest.raises(AuthorGenerationError) as refusal:
            author_question(provider, blueprint=item, evidence=evidence_pack())
        assert refusal.value.code == "AUTHOR_INPUT_MISMATCH"
    assert provider.calls == []


def test_author_cannot_cite_or_answer_outside_the_evidence_pack() -> None:
    for output in (
        author_output(source_refs=["chunk-not-authorized"]),
        author_output(
            solution_steps=[
                AuthorSolutionStep(
                    ordinal=1,
                    operation="Invent an answer",
                    result="unsupported",
                    explanation="This step cites a source outside the objective-scoped pack.",
                    source_refs=["chunk-not-authorized"],
                )
            ]
        ),
    ):
        with pytest.raises(AuthorGenerationError) as refusal:
            author_question(SpyProvider(output), blueprint=blueprint(), evidence=evidence_pack())
        assert refusal.value.code == "AUTHOR_OUTPUT_OUT_OF_SCOPE"


def test_question_shape_matches_blueprint_without_deferring_basic_contract_errors() -> None:
    with pytest.raises(AuthorGenerationError) as refusal:
        author_question(
            SpyProvider(author_output(options=["A", "B"])),
            blueprint=blueprint(),
            evidence=evidence_pack(),
        )
    assert refusal.value.code == "AUTHOR_OUTPUT_INVALID"

    mcq = blueprint(
        question_type="MCQ_SINGLE",
        expected_answer_form="SINGLE_CHOICE",
        marks=10,
    )
    with pytest.raises(AuthorGenerationError) as refusal:
        author_question(
            SpyProvider(author_output(options=["A", "B"], correct_option_index=None)),
            blueprint=mcq,
            evidence=evidence_pack(),
        )
    assert refusal.value.code == "AUTHOR_OUTPUT_INVALID"


def test_provider_failure_is_bounded_and_does_not_echo_private_provider_text() -> None:
    class FailingProvider:
        def generate(self, *_args: Any, **_kwargs: Any) -> tuple[Any, dict[str, Any]]:
            run = completed_run()
            run.update(status="FAILED", error_class="SCHEMA_INVALID")
            raise ProviderCallFailure(ValueError("PRIVATE ANSWER TEXT"), run)

    with pytest.raises(AuthorGenerationError) as refusal:
        author_question(FailingProvider(), blueprint=blueprint(), evidence=evidence_pack())
    assert refusal.value.code == "AUTHOR_OUTPUT_INVALID"
    assert "PRIVATE ANSWER TEXT" not in str(refusal.value)
    assert refusal.value.provider_run is not None
    assert refusal.value.provider_run["status"] == "FAILED"


def test_non_deepseek_live_provider_is_rejected_before_any_paid_call() -> None:
    class HistoricalQwenProvider(SpyProvider):
        cache_model = "qwen3.8-max"
        cache_protocol = "responses"
        is_deepseek = False

    provider = HistoricalQwenProvider()

    with pytest.raises(AuthorGenerationError) as refusal:
        author_question(provider, blueprint=blueprint(), evidence=evidence_pack())

    assert refusal.value.code == "AUTHOR_PROVIDER_BLOCKED"
    assert provider.calls == []


def test_real_learning_provider_offline_contract_uses_labelled_fixture(tmp_path: Any) -> None:
    settings = Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        app_env="test",
        rag_provider_mode="deterministic",
        ui_web_dir=tmp_path / "no-web-build",
    )

    candidate = author_question(
        LearningProvider(settings),
        blueprint=blueprint(),
        evidence=evidence_pack(),
    )

    assert candidate.provider_run.model == "FAKE_TEST_ONLY"
    assert candidate.provider_run.status == "COMPLETED"
    assert "FAKE TEST FIXTURE" in candidate.public_question.question_text
    assert "FAKE TEST FIXTURE" in candidate.private_solution.candidate_answer
