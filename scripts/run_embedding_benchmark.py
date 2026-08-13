"""Run a billable, budget-capped embedding retrieval benchmark on official courses."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from openai import OpenAI, OpenAIError

ROOT = Path(__file__).resolve().parents[1]
RAG_SERVICE = ROOT / "services" / "rag-api"
sys.path.insert(0, str(RAG_SERVICE))

from app.evaluation.embedding_benchmark import (
    calculate_embedding_cost_ceiling,
    evaluate_embeddings,
    load_embedding_cases,
    load_official_corpus,
)

PROTOCOL_OVERHEAD_TOKENS = 8


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url")
    parser.add_argument("--api-key-env", required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=ROOT / "benchmarks" / "embedding-retrieval-cases.json",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--dimensions", type=int)
    parser.add_argument("--input-price-per-million", type=float, required=True)
    parser.add_argument("--max-total-cost", type=float, required=True)
    parser.add_argument("--currency", required=True)
    parser.add_argument("--allow-billable", action="store_true")
    return parser.parse_args()


def _write_atomically(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.partial")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def main() -> int:
    args = parse_args()
    if not args.allow_billable:
        print("Refusing provider calls: pass --allow-billable after approving model charges.")
        return 2
    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        print(f"Missing credential environment variable: {args.api_key_env}")
        return 2
    if not args.database.is_file():
        print("Embedding benchmark database is unavailable.")
        return 2
    if args.output.exists() or args.output.with_name(f".{args.output.name}.partial").exists():
        print("Refusing to overwrite an existing embedding benchmark output.")
        return 2
    if args.top_k <= 0 or not 1 <= args.batch_size <= 100:
        print("--top-k must be positive and --batch-size must be between 1 and 100.")
        return 2
    if args.dimensions is not None and args.dimensions <= 0:
        print("--dimensions must be positive when supplied.")
        return 2
    if not math.isfinite(args.max_total_cost) or args.max_total_cost <= 0:
        print("--max-total-cost must be finite and positive.")
        return 2
    if re.fullmatch(r"[A-Z]{3}", args.currency) is None:
        print("--currency must be a three-letter uppercase ISO 4217 code.")
        return 2

    try:
        cases = load_embedding_cases(args.dataset)
        chunks, expected_ids = load_official_corpus(args.database, cases)
        texts = [case.query for case in cases] + [chunk.content for chunk in chunks]
        token_ceilings = [len(text.encode()) + PROTOCOL_OVERHEAD_TOKENS for text in texts]
        cost_ceiling = calculate_embedding_cost_ceiling(
            token_ceilings,
            price_per_million=args.input_price_per_million,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Embedding benchmark preflight failed: {type(error).__name__}.")
        return 2
    if cost_ceiling > args.max_total_cost:
        print(
            f"Refusing provider calls: conservative {args.currency} cost ceiling "
            f"{cost_ceiling:.8f} exceeds approved maximum {args.max_total_cost:.8f}."
        )
        return 2

    client = OpenAI(
        api_key=api_key,
        timeout=60.0,
        max_retries=0,
        **({"base_url": args.base_url} if args.base_url else {}),
    )
    vectors: list[list[float]] = []
    input_tokens = 0
    started = time.perf_counter()
    try:
        for offset in range(0, len(texts), args.batch_size):
            request: dict[str, Any] = {
                "input": texts[offset : offset + args.batch_size],
                "model": args.model,
                "encoding_format": "float",
            }
            if args.dimensions is not None:
                request["dimensions"] = args.dimensions
            response = client.embeddings.create(**request)
            vectors.extend(
                list(item.embedding) for item in sorted(response.data, key=lambda item: item.index)
            )
            input_tokens += int(getattr(response.usage, "prompt_tokens", 0))
    except (OpenAIError, OSError, RuntimeError) as error:
        print(
            "Embedding benchmark stopped after a provider failure; "
            f"inspect the local exception type: {type(error).__name__}.",
            file=sys.stderr,
        )
        return 1
    if len(vectors) != len(texts):
        print("Embedding provider returned an unexpected vector count.", file=sys.stderr)
        return 1
    query_vectors = vectors[: len(cases)]
    chunk_vectors = vectors[len(cases) :]
    try:
        summary = evaluate_embeddings(
            cases,
            chunks,
            expected_ids=expected_ids,
            query_vectors=query_vectors,
            chunk_vectors=chunk_vectors,
            top_k=args.top_k,
        )
    except ValueError:
        print("Embedding provider returned an invalid vector contract.", file=sys.stderr)
        return 1
    summary.update(
        {
            "provider": args.provider,
            "model": args.model,
            "dimensions": len(vectors[0]) if vectors else None,
            "latency_ms": round((time.perf_counter() - started) * 1_000, 3),
            "input_tokens": input_tokens,
            "currency": args.currency,
            "approved_max_cost": args.max_total_cost,
            "preflight_cost_ceiling": cost_ceiling,
            "estimated_cost": round(
                input_tokens * args.input_price_per_million / 1_000_000, 8
            ),
            "content_included": False,
            "manual_review_status": "required",
        }
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    _write_atomically(args.output, summary)
    print(
        f"Wrote {len(cases)} cases; Recall@{args.top_k}={summary['recall_at_k']:.1%}; "
        "compare repeated candidates before selecting an embedding model."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
