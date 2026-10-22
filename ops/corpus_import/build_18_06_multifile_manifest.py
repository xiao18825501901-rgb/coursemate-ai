"""Build the exact reviewed MIT OCW 18.06 multi-document import manifest."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


COURSE_ID = "mit-ocw-18-06-linear-algebra-spring-2010"


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: build_18_06_multifile_manifest.py WORK_ROOT")
    root = Path(sys.argv[1]).resolve()
    candidate = root / "ocw-candidates" / "18.06-spring-2010"
    expanded = candidate / "expanded"
    review = candidate / "MIT_OCW_18_06_EXACT_PACKAGE_REVIEW_20261021.json"
    review_data = json.loads(review.read_text(encoding="utf-8"))
    expected = review_data["qualified_pdf_subset"]
    scan = expected["text_rights_scan"]
    assert int(scan["extraction_error_files"]) == 0
    assert int(scan["manual_marker_files"]) == 1
    assert scan["manual_marker_file"] == "4d876a9159e32543eb0d73b4d4382f4c_MIT18_06S10ZoomNotes.pdf"
    assert "matching resource data.json explicitly assigns CC BY-NC-SA 4.0" in scan["resolution"]

    resource_records = {}
    for metadata_path in (expanded / "resources").glob("*/data.json"):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        filename = Path(metadata.get("file") or "").name
        if metadata.get("file_type") == "application/pdf" and filename:
            assert filename not in resource_records
            resource_records[filename] = metadata

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

    assert len(resource_records) == int(expected["resource_license_records"])
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
        "retrieval_query": "linear algebra vectors matrices eigenvalues orthogonality",
        "documents": documents,
    }
    destination = candidate / "MIT_OCW_18_06_MULTI_FILE_IMPORT_MANIFEST.json"
    destination.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(destination)


if __name__ == "__main__":
    main()
