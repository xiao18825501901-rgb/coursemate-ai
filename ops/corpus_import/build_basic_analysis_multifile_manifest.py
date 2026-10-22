"""Build the exact reviewed Basic Analysis two-volume import manifest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


COURSE_ID = "jirka-basic-analysis-volumes-1-2-2026"
LICENSE_URL = "https://creativecommons.org/licenses/by-sa/4.0/"


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def main() -> None:
    root = Path(__file__).resolve().parent
    batch = root / "open-source-batch94"
    batch_manifest_path = batch / "OPEN_CORPUS_BATCH_MANIFEST.json"
    batch_manifest = json.loads(batch_manifest_path.read_text(encoding="utf-8"))
    course = next(item for item in batch_manifest["courses"] if item["course_id"] == COURSE_ID)
    course_root = batch / "basic-analysis"
    receipt_path = course_root / "SOURCE_RECEIPT.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    attribution = (course_root / "ATTRIBUTION.md").read_text(encoding="utf-8").strip()
    receipt_by_path = {item["path"]: item for item in receipt["files"]}
    documents = []
    for relative_path in course["files"]:
        source = batch / relative_path
        identity = receipt_by_path[source.name]
        assert source.stat().st_size == int(identity["bytes"])
        assert digest(source) == identity["sha256"]
        documents.append(
            {
                "relative_path": source.relative_to(course_root).as_posix(),
                "filename": source.name,
                "bytes": int(identity["bytes"]),
                "sha256": identity["sha256"],
                "media_type": "application/pdf",
                "resource_title": course["title"],
                "resource_license": LICENSE_URL,
            }
        )
    assert len(documents) == len(receipt["files"]) == 2
    assert sum(item["bytes"] for item in documents) == int(course["bytes"])
    manifest = {
        "schema_version": 1,
        "review_contract": "source_receipt_v1",
        "course_id": COURSE_ID,
        "title": course["title"],
        "description": attribution,
        "license_url": LICENSE_URL,
        "official_source_url": receipt["source_page"],
        "review_path": receipt_path.relative_to(root).as_posix(),
        "review_sha256": digest(receipt_path),
        "expected_files": len(documents),
        "expected_bytes": int(course["bytes"]),
        "retrieval_query": course["retrieval_query"],
        "documents": documents,
    }
    destination = course_root / "BASIC_ANALYSIS_MULTI_FILE_IMPORT_MANIFEST.json"
    destination.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(destination)


if __name__ == "__main__":
    main()
