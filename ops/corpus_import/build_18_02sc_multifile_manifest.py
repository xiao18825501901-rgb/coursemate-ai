"""Build the exact reviewed MIT OCW 18.02SC multi-document import manifest."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


COURSE_ID = "mit-ocw-18-02sc-multivariable-calculus-fall-2010"


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: build_18_02sc_multifile_manifest.py WORK_ROOT")
    root = Path(sys.argv[1]).resolve()
    candidate = root / "ocw-candidates" / "18.02sc-fall-2010"
    expanded = candidate / "expanded"
    review = candidate / "MIT_OCW_18_02SC_EXACT_PACKAGE_REVIEW_20261021.json"
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
    seen_sha256 = set()
    for filename in sorted(resource_records):
        metadata = resource_records[filename]
        source = expanded / "static_resources" / filename
        assert source.is_file()
        assert metadata["license"] == review_data["license_url"]
        sha256 = digest(source)
        if sha256 in seen_sha256:
            continue
        seen_sha256.add(sha256)
        documents.append(
            {
                "relative_path": source.relative_to(candidate).as_posix(),
                "filename": source.name,
                "bytes": source.stat().st_size,
                "sha256": sha256,
                "media_type": "application/pdf",
                "resource_title": metadata["title"],
                "resource_license": metadata["license"],
            }
        )

    assert len(resource_records) == int(expected["resource_license_records"])
    assert len(documents) == int(expected["files"])
    assert len(seen_sha256) == int(expected["unique_sha256"])
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
        "retrieval_query": "multivariable calculus vectors partial derivatives multiple integrals",
        "documents": documents,
    }
    destination = candidate / "MIT_OCW_18_02SC_MULTI_FILE_IMPORT_MANIFEST.json"
    destination.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(destination)


if __name__ == "__main__":
    main()
