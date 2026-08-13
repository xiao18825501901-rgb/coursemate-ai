from __future__ import annotations

import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[3]
PACKS_PATH = REPOSITORY_ROOT / "docs" / "file-request-packs" / "README.md"


def test_file_request_packs_are_complete_bounded_and_resolvable() -> None:
    rows = [
        line
        for line in PACKS_PATH.read_text(encoding="utf-8").splitlines()
        if re.match(r"^\| V2-\d{2} ", line)
    ]

    assert [row.split("|")[1].strip().split()[0] for row in rows] == [
        f"V2-{number:02d}" for number in range(1, 15)
    ]
    for row in rows:
        paths = re.findall(r"`([^`]+)`", row)
        assert 1 <= len(paths) <= 5, row
        assert len(paths) == len(set(paths)), row
        for relative_path in paths:
            path = REPOSITORY_ROOT / relative_path
            assert path.is_file(), f"Missing file request pack path: {relative_path}"
