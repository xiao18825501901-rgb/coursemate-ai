"""Build the exact reviewed MIT OCW 15.S12 multi-document import manifest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


COURSE_ID = "mit-ocw-15-s12-blockchain-and-money-fall-2018"
QUALIFIED_FILENAMES = (
    "003b095f92714be7c11e863b0103bdfc_EH6vE97qIP4.pdf",
    "0719d7350db1366b1f194aed581b2eec_Ycy0Dy-B1c.pdf",
    "0a7523ee0c6ebaab89917bcb22e53573_zGDTt9Q3vyM.pdf",
    "11cb22fb5511632ea5a51a9d3ea3b41f_KHBi3n0hUSU.pdf",
    "13577dbec83f909613a141fa2cfe0c6d_uNqMBBbb6UI.pdf",
    "1e2093c2317c466bd762369b8de2db3a_DsSzQfejwMk.pdf",
    "461d94955cf5303f85d3f1f686181fcd_vPJ8oQ99r9c.pdf",
    "56ef3b0328e78c01fc42baea53c56af8_-cZPoqnRZq4.pdf",
    "80a4923ef3b787cb9fd3d5ff74c8d4f3_5auv_xrvoJk.pdf",
    "8bcf796b5a589e2d15aa7746df495711_sMnBl0g3Ev4.pdf",
    "8db830650d24c30dcc3266c4cb31e9ea_7EXcHqLg7BI.pdf",
    "97ee3c543c07f134ffb9c9b697154501_eGNSuTBc60.pdf",
    "a5c7b0dab423c6d6716b905cebd42644_l0vD_FBWk0g.pdf",
    "b275e819830d45a96730dd3ead1c4f09_lPD9fx8fK1k.pdf",
    "c9f5741bf8daee6e948a3e1d9ea0ca34_0UvVOMZqpEA.pdf",
    "cd57e04accaf8885cb3b65f5e4741d43_W06Le8fw0vU.pdf",
    "cdf04eb2ca36571102b7b216c645cb99_CJCKTixMb70.pdf",
    "da9cbe6d707f6e6afefb3e31cd7d8112_ObGYNQLG3us.pdf",
    "e61959b6eabd1e77876b2765ee654d8e_iWpQpPbo7rM.pdf",
    "e9322ecbd0468bd4c98bfeb02d028c8e_MIT15_S12F18_ses11.pdf",
    "eb88229d73cbdbca68b362c3f6f90edf_ojcOUtUwIe4.pdf",
    "ed8cf9250a04f1b9be6fb0d582c79db4_MIT15_S12F18_ses6.pdf",
)


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def main() -> None:
    root = Path(__file__).resolve().parent
    candidate = root / "ocw-candidates" / "15.s12-fall-2018"
    expanded = candidate / "expanded"
    review = candidate / "MIT_OCW_15_S12_EXACT_PACKAGE_REVIEW_20261021.json"
    review_data = json.loads(review.read_text(encoding="utf-8"))
    expected = review_data["qualified_pdf_subset"]
    resource_records = {}
    for metadata_path in (expanded / "resources").glob("*/data.json"):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        filename = Path(metadata.get("file") or "").name
        if metadata.get("file_type") == "application/pdf" and filename:
            assert filename not in resource_records
            resource_records[filename] = metadata
    assert len(resource_records) == int(expected["resource_license_records"])
    documents = []
    for filename in QUALIFIED_FILENAMES:
        source = expanded / "static_resources" / filename
        metadata = resource_records[filename]
        assert metadata["license"] == review_data["license_url"]
        documents.append(
            {
                "relative_path": source.relative_to(candidate).as_posix(),
                "filename": filename,
                "bytes": source.stat().st_size,
                "sha256": digest(source),
                "media_type": "application/pdf",
                "resource_title": metadata["title"],
                "resource_license": metadata["license"],
            }
        )
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
        "retrieval_query": "blockchain money ledgers smart contracts financial system",
        "documents": documents,
    }
    destination = candidate / "MIT_OCW_15_S12_MULTI_FILE_IMPORT_MANIFEST.json"
    destination.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(destination)


if __name__ == "__main__":
    main()
