"""Build the exact reviewed MIT OCW 6.002 multi-document import manifest."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


COURSE_ID = "mit-ocw-6-002-circuits-electronics-spring-2007"
EXCLUDED_FILENAME = "992c85451e40984a2b3a6f4878bb1a76_lab_handout.pdf"
EXCLUDED_SHA256 = "4b81410c8e1aba21fd399521e0be424e694ecd4cd17b11b5915889052e9338f0"


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: build_6_002_multifile_manifest.py WORK_ROOT")
    root = Path(sys.argv[1]).resolve()
    candidate = root / "ocw-candidates" / "6.002-spring-2007"
    expanded = candidate / "expanded"
    review = candidate / "MIT_OCW_6_002_EXACT_PACKAGE_REVIEW_20261021.json"
    review_data = json.loads(review.read_text(encoding="utf-8"))
    expected = review_data["qualified_pdf_subset"]
    scan = expected["text_rights_scan"]
    assert int(scan["extraction_error_files"]) == 0
    assert int(scan["manual_marker_files"]) == 1
    assert int(scan["excluded_manual_marker_files"]) == 1

    resource_records = {}
    for metadata_path in (expanded / "resources").glob("*/data.json"):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        filename = Path(metadata.get("file") or "").name
        if metadata.get("file_type") == "application/pdf" and filename:
            assert filename not in resource_records
            resource_records[filename] = metadata

    excluded_metadata = resource_records.pop(EXCLUDED_FILENAME)
    excluded_source = expanded / "static_resources" / EXCLUDED_FILENAME
    assert excluded_metadata["license"] == review_data["license_url"]
    assert excluded_source.stat().st_size == 643613
    assert digest(excluded_source) == EXCLUDED_SHA256

    documents = []
    for filename in sorted(resource_records):
        metadata = resource_records[filename]
        source = expanded / "static_resources" / filename
        assert source.is_file()
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

    assert len(resource_records) + 1 == int(expected["resource_license_records"])
    assert len(documents) == int(expected["files"])
    assert len({item["sha256"] for item in documents}) == int(expected["unique_sha256"])
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
        "retrieval_query": "circuits electronics voltage current MOSFET amplifiers filters",
        "excluded_documents": [
            {
                "filename": EXCLUDED_FILENAME,
                "sha256": EXCLUDED_SHA256,
                "reason": review_data["package_exclusions"][0]["reason"],
            }
        ],
        "documents": documents,
    }
    destination = candidate / "MIT_OCW_6_002_MULTI_FILE_IMPORT_MANIFEST.json"
    destination.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(destination)


if __name__ == "__main__":
    main()
