from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.evaluation.embedding_benchmark import (
    CorpusChunk,
    EmbeddingCase,
    calculate_embedding_cost_ceiling,
    evaluate_embeddings,
    load_embedding_cases,
    load_official_corpus,
)

REPOSITORY_ROOT = Path(__file__).parents[3]
DATASET = REPOSITORY_ROOT / "benchmarks" / "embedding-retrieval-cases.json"
CORPUS_DATABASE = REPOSITORY_ROOT / "data" / "rag.sqlite3"
RUNNER = REPOSITORY_ROOT / "scripts" / "run_embedding_benchmark.py"


def test_embedding_dataset_has_unique_resolvable_official_course_judgments() -> None:
    cases = load_embedding_cases(DATASET)
    assert len(cases) == 8
    assert len({case.id for case in cases}) == len(cases)
    if not CORPUS_DATABASE.is_file():
        pytest.skip("Local read-only CourseMate corpus is unavailable")

    chunks, expected_ids = load_official_corpus(CORPUS_DATABASE, cases)

    assert len(chunks) > 100
    assert set(expected_ids) == {case.id for case in cases}
    assert all(expected_ids[case.id] for case in cases)
    assert {chunk.course_id for chunk in chunks} == {"cs3481", "ge2324"}


def test_embedding_evaluation_is_course_scoped_and_reports_recall_and_mrr() -> None:
    cases = [
        EmbeddingCase("a", "course-a", "alpha", "a.md", "section", "A"),
        EmbeddingCase("b", "course-b", "beta", "b.md", "section", "B"),
    ]
    chunks = [
        CorpusChunk("a-target", "course-a", "a.md", "section", "A", "alpha"),
        CorpusChunk("a-other", "course-a", "other.md", "section", "X", "other"),
        CorpusChunk("b-target", "course-b", "b.md", "section", "B", "beta"),
    ]
    summary = evaluate_embeddings(
        cases,
        chunks,
        expected_ids={"a": {"a-target"}, "b": {"b-target"}},
        query_vectors=[[1.0, 0.0], [0.0, 1.0]],
        chunk_vectors=[[0.8, 0.2], [0.1, 0.9], [0.0, 1.0]],
        top_k=2,
    )

    assert summary["recall_at_k"] == 1.0
    assert summary["mean_reciprocal_rank"] == 1.0
    assert summary["results"][0]["returned_chunk_ids"] == ["a-target", "a-other"]
    assert summary["results"][1]["returned_chunk_ids"] == ["b-target"]
    assert "alpha" not in str(summary)


def test_embedding_evaluation_rejects_mismatched_vector_contract() -> None:
    case = EmbeddingCase("a", "course-a", "alpha", "a.md", "section", "A")
    chunk = CorpusChunk("a-target", "course-a", "a.md", "section", "A", "alpha")

    with pytest.raises(ValueError, match="vector count"):
        evaluate_embeddings(
            [case],
            [chunk],
            expected_ids={"a": {"a-target"}},
            query_vectors=[],
            chunk_vectors=[[1.0]],
            top_k=1,
        )


def test_embedding_cost_ceiling_requires_positive_finite_price() -> None:
    assert calculate_embedding_cost_ceiling([100, 200], price_per_million=2.0) == 0.0006
    with pytest.raises(ValueError, match="positive finite"):
        calculate_embedding_cost_ceiling([100], price_per_million=0.0)
    with pytest.raises(ValueError, match="non-negative"):
        calculate_embedding_cost_ceiling([-1], price_per_million=1.0)


def test_embedding_runner_refuses_over_budget_before_provider_client(
    tmp_path: Path,
) -> None:
    output = tmp_path / "embedding.json"
    process = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--provider",
            "test-provider",
            "--model",
            "test-model",
            "--api-key-env",
            "EMBEDDING_TEST_KEY",
            "--database",
            str(CORPUS_DATABASE),
            "--output",
            str(output),
            "--input-price-per-million",
            "1",
            "--max-total-cost",
            "0.00000001",
            "--currency",
            "USD",
            "--allow-billable",
        ],
        check=False,
        capture_output=True,
        env={**os.environ, "EMBEDDING_TEST_KEY": "not-a-real-key"},
        text=True,
    )

    assert process.returncode == 2
    assert "exceeds approved maximum" in process.stdout
    assert "not-a-real-key" not in process.stdout + process.stderr
    assert not output.exists()


def test_embedding_runner_refuses_without_explicit_billable_opt_in(
    tmp_path: Path,
) -> None:
    output = tmp_path / "embedding.json"
    process = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--provider",
            "test-provider",
            "--model",
            "test-model",
            "--api-key-env",
            "EMBEDDING_TEST_KEY",
            "--database",
            str(CORPUS_DATABASE),
            "--output",
            str(output),
            "--input-price-per-million",
            "1",
            "--max-total-cost",
            "1",
            "--currency",
            "USD",
        ],
        check=False,
        capture_output=True,
        env={**os.environ, "EMBEDDING_TEST_KEY": "not-a-real-key"},
        text=True,
    )

    assert process.returncode == 2
    assert "Refusing provider calls" in process.stdout
    assert "not-a-real-key" not in process.stdout + process.stderr
    assert not output.exists()


def test_embedding_runner_rejects_unsafe_base_url_before_provider_client(
    tmp_path: Path,
) -> None:
    process = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--provider",
            "test-provider",
            "--model",
            "test-model",
            "--base-url",
            "http://secret-provider.example/v1",
            "--api-key-env",
            "EMBEDDING_TEST_KEY",
            "--database",
            str(CORPUS_DATABASE),
            "--output",
            str(tmp_path / "embedding.json"),
            "--input-price-per-million",
            "1",
            "--max-total-cost",
            "1",
            "--currency",
            "USD",
            "--allow-billable",
        ],
        check=False,
        capture_output=True,
        env={**os.environ, "EMBEDDING_TEST_KEY": "not-a-real-key"},
        text=True,
    )

    assert process.returncode == 2
    assert "invalid or unsafe" in process.stdout
    assert "secret-provider" not in process.stdout + process.stderr
    assert "not-a-real-key" not in process.stdout + process.stderr
