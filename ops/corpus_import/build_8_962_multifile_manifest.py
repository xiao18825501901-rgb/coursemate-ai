"""Build the exact reviewed MIT OCW 8.962 multi-document import manifest."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


COURSE_ID = "mit-ocw-8-962-general-relativity-spring-2020"


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: build_8_962_multifile_manifest.py WORK_ROOT")
    root = Path(sys.argv[1]).resolve()
    candidate = root / "ocw-candidates" / "8.962-spring-2020"
    expanded = candidate / "expanded"
    review = candidate / "MIT_OCW_8_962_EXACT_PACKAGE_REVIEW_20261021.json"
    review_data = json.loads(review.read_text(encoding="utf-8"))
    expected = review_data["qualified_pdf_subset"]
    assert int(expected["text_rights_scan"]["manual_marker_files"]) == 0
    assert int(expected["text_rights_scan"]["extraction_error_files"]) == 0

    resource_records = {}
    for metadata_path in (expanded / "resources").glob("*/data.json"):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        filename = Path(metadata.get("file") or "").name
        if metadata.get("file_type") == "application/pdf" and filename:
            assert filename not in resource_records
            resource_records[filename] = metadata

    documents = []
    for source in sorted((expanded / "static_resources").glob("*.pdf")):
        metadata = resource_records[source.name]
        assert metadata["license"] == review_data["license_url"]
        documents.append(
            {
                "relative_path": source.relative_to(candidate).as_posix(),
                "filename": source.name,
                "bytes": source.stat().st_size,
                "sha256": digest(source),
                "media_type": "application/pdf",
                "resource_title": metadata["title"],
                "resource_license": metadata["license"],
            }
        )

    assert len(resource_records) == int(expected["resource_license_records"])
    assert len(documents) == int(expected["files"])
    assert sum(item["bytes"] for item in documents) == int(expected["bytes"])
    manifest = {
        "schema_version": 1,
        "course_id": COURSE_ID,
        "title": review_data["title"],
        "description": review_data["required_attribution"],
        "license_url": review_data["license_url"],
        "official_source_url": review_data["official_download_page"],
        "review_path": review.relative_to(root).as_posix(),
        "review_sha256": digest(review),
        "expected_files": int(expected["files"]),
        "expected_bytes": int(expected["bytes"]),
        "retrieval_query": "general relativity spacetime curvature Einstein field equations",
        "documents": documents,
    }
    destination = candidate / "MIT_OCW_8_962_MULTI_FILE_IMPORT_MANIFEST.json"
    destination.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(destination)


if __name__ == "__main__":
    main()
