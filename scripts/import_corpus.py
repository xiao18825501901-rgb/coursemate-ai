import argparse
import io
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RAG_ROOT = REPOSITORY_ROOT / "services" / "rag-api"
sys.path.insert(0, str(RAG_ROOT))

from app.config import Settings
from app.corpus_import import ImportItem, import_corpus, load_inventory
from app.db import Database
from app.rag.embeddings import (
    DeterministicEmbeddingProvider,
    EmbeddingProvider,
    OpenAIEmbeddingProvider,
)
from app.services.ingestion import IngestionService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import the read-only CourseMate corpus inventory."
    )
    parser.add_argument(
        "--mode",
        choices=("deterministic", "openai"),
        default="openai",
        help="Embedding provider. Deterministic mode is for local demos and acceptance tests.",
    )
    parser.add_argument(
        "--inventory",
        type=Path,
        default=REPOSITORY_ROOT / "data" / "inventory" / "course-files.json",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=REPOSITORY_ROOT / "data" / "inventory" / "import-report.json",
    )
    return parser.parse_args()


def main() -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    args = parse_args()
    inventory = load_inventory(args.inventory)
    trusted_import_limit = max(
        20 * 1024 * 1024,
        max((record.sizeBytes for record in inventory.files), default=0) + 1,
    )
    settings = Settings(
        database_path=REPOSITORY_ROOT / "data" / "rag.sqlite3",
        upload_dir=REPOSITORY_ROOT / "data" / "uploads",
        max_upload_bytes=trusted_import_limit,
    )
    database = Database(settings)
    database.initialize()
    provider: EmbeddingProvider
    if args.mode == "deterministic":
        provider = DeterministicEmbeddingProvider()
    else:
        secret = settings.openai_api_key
        if secret is None or not secret.get_secret_value():
            print("OPENAI_API_KEY is required for --mode openai.", file=sys.stderr)
            return 2
        provider = OpenAIEmbeddingProvider(
            api_key=secret.get_secret_value(),
            model=settings.openai_embedding_model,
        )
    service = IngestionService(database, settings, provider)

    def progress(index: int, total: int, item: ImportItem) -> None:
        print(f"[{index:02d}/{total:02d}] {item.course_id} {item.status:14s} {item.filename}")

    report = import_corpus(
        inventory,
        service=service,
        embedding_mode=args.mode,
        transcription_dir=REPOSITORY_ROOT / "data" / "transcriptions",
        on_progress=progress,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    print(report.summary.model_dump_json(indent=2))
    print(f"Report: {args.report}")
    return 1 if report.summary.failed or report.summary.invalid or report.summary.missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
