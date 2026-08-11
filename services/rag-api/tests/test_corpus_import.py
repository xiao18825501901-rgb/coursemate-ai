import json
from pathlib import Path

from app.config import Settings
from app.corpus_import import CorpusInventory, import_corpus
from app.db import Database
from app.rag.embeddings import DeterministicEmbeddingProvider
from app.services.ingestion import IngestionService


def test_import_corpus_indexes_supported_files_and_reports_every_other_record(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    notes = source / "notes.md"
    notes.write_text("# Lighting\n\nDiffuse and specular reflection.", encoding="utf-8")
    dataset = source / "values.csv"
    dataset.write_text("x,y\n1,2\n", encoding="utf-8")
    missing = source / "missing.pdf"
    inventory_path = tmp_path / "inventory.json"
    inventory_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "sources": [],
                "files": [
                    {
                        "courseId": "cs3481",
                        "sourcePath": str(source),
                        "relativePath": notes.name,
                        "fullPath": str(notes),
                        "filename": notes.name,
                        "extension": ".md",
                        "sizeBytes": notes.stat().st_size,
                        "lastWriteTimeUtc": "2026-08-11T00:00:00Z",
                        "importerMode": "index",
                    },
                    {
                        "courseId": "cs3481",
                        "sourcePath": str(source),
                        "relativePath": dataset.name,
                        "fullPath": str(dataset),
                        "filename": dataset.name,
                        "extension": ".csv",
                        "sizeBytes": dataset.stat().st_size,
                        "lastWriteTimeUtc": "2026-08-11T00:00:00Z",
                        "importerMode": "inventory-only",
                    },
                    {
                        "courseId": "ge2324",
                        "sourcePath": str(source),
                        "relativePath": missing.name,
                        "fullPath": str(missing),
                        "filename": missing.name,
                        "extension": ".pdf",
                        "sizeBytes": 10,
                        "lastWriteTimeUtc": "2026-08-11T00:00:00Z",
                        "importerMode": "index",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    settings = Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        chunk_size=200,
        chunk_overlap=20,
    )
    database = Database(settings)
    database.initialize()
    service = IngestionService(database, settings, DeterministicEmbeddingProvider())

    inventory = CorpusInventory.model_validate_json(inventory_path.read_text(encoding="utf-8"))
    report = import_corpus(inventory, service=service, embedding_mode="deterministic")

    assert report.summary.total == 3
    assert report.summary.ready == 1
    assert report.summary.inventory_only == 1
    assert report.summary.missing == 1
    assert {item.status for item in report.items} == {"ready", "inventory-only", "missing"}
    assert service.list_documents("cs3481", page=1, page_size=10).items[0].chunk_count == 1
    assert service.list_courses(page=1, page_size=10).total == 2

    document = service.list_documents("cs3481", page=1, page_size=10).items[0]
    with database.connect() as connection:
        connection.execute("UPDATE documents SET status = 'failed' WHERE id = ?", (document.id,))
    retried = import_corpus(inventory, service=service, embedding_mode="deterministic")

    assert retried.summary.ready == 1
    assert retried.summary.failed == 0
    assert service.list_documents("cs3481", page=1, page_size=10).items[0].chunk_count == 1


def test_import_rejects_inventory_path_that_escapes_its_declared_source(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("unsafe path", encoding="utf-8")
    inventory = CorpusInventory.model_validate(
        {
            "schemaVersion": 1,
            "sources": [],
            "files": [
                {
                    "courseId": "cs3481",
                    "sourcePath": str(source),
                    "relativePath": outside.name,
                    "fullPath": str(outside),
                    "filename": outside.name,
                    "extension": ".md",
                    "sizeBytes": outside.stat().st_size,
                    "lastWriteTimeUtc": "2026-08-11T00:00:00Z",
                    "importerMode": "index",
                }
            ],
        }
    )
    settings = Settings(database_path=tmp_path / "rag.sqlite3", upload_dir=tmp_path / "uploads")
    database = Database(settings)
    database.initialize()
    service = IngestionService(database, settings, DeterministicEmbeddingProvider())

    report = import_corpus(inventory, service=service, embedding_mode="deterministic")

    assert report.summary.invalid == 1
    assert report.items[0].status == "invalid"
    assert service.list_documents("cs3481", page=1, page_size=10).total == 0
