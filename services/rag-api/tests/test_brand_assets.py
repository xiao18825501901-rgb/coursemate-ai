"""The brand assets are the owner's artwork, derived — this checks the files, not the promise.  The
owner supplied the original at a fixed path and the rule is to use it as-is. A web unit test runs
in jsdom and cannot see the filesystem, so the guard that matters lives here: the original is
present and matches the hash the report records, every derived file exists at the size the brand
source declares, the aspect ratio was preserved (the artwork is trimmed to its own bounding box
with a uniform margin, never stretched), the opaque variants are opaque, and the recorded hashes
still match the bytes on disk.  If someone later re-runs a different derivation, edits a file by
hand or drops an icon, this fails."""

from __future__ import annotations

import hashlib
import json
import pathlib
import re

import pytest
from PIL import Image

REPO = pathlib.Path(__file__).resolve().parents[3]
BRAND_DIR = REPO / "apps" / "web" / "public" / "brand"
PROVENANCE = REPO / "apps" / "web" / "brand-source"
DERIVED = PROVENANCE / "derived-manifest.json"
BRAND_TS = REPO / "apps" / "web" / "src" / "brand.ts"
SOURCE_NAME = "coursejesus-logo-source.png"
# The owner's own file, hashed when it was read: this is the provenance anchor.
SOURCE_SHA256 = "ae536df4cc1e9e989c3b9c7ff15a33137d1f526bcbc779aebd4b3e6e93be14e5"


@pytest.fixture(scope="module")
def derived() -> dict:
    assert DERIVED.is_file(), f"the derivation record is missing: {DERIVED}"
    return json.loads(DERIVED.read_text(encoding="utf-8"))


def test_the_owner_original_is_present_unmodified(derived: dict) -> None:
    source = PROVENANCE / SOURCE_NAME
    assert source.is_file(), "the owner's artwork is not in the tree"
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    assert digest == SOURCE_SHA256, "the stored original is not the file the owner supplied"
    assert derived["source"]["sha256"] == SOURCE_SHA256
    assert digest == derived["source"]["sha256"]


def test_every_derived_asset_exists_at_its_declared_size(derived: dict) -> None:
    for asset in derived["assets"]:
        path = BRAND_DIR / asset["file"]
        assert path.is_file(), f"{asset['file']} is missing"
        with Image.open(path) as image:
            assert list(image.size) == asset["size"], f"{asset['file']} has the wrong dimensions"
            assert image.format == "PNG"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == asset["sha256"], (
            f"{asset['file']} changed since it was derived"
        )


def test_the_aspect_ratio_was_preserved(derived: dict) -> None:
    """A stretched mark is the failure this pins: every asset is square, like the trimmed source."""
    with Image.open(PROVENANCE / SOURCE_NAME) as image:
        source = image.convert("RGBA")
    bbox = source.getchannel("A").getbbox()
    assert bbox is not None
    trimmed_width = bbox[2] - bbox[0]
    trimmed_height = bbox[3] - bbox[1]
    # The artwork is close to square; the derivation pads it to a square instead of stretching it.
    assert abs(trimmed_width - trimmed_height) <= max(trimmed_width, trimmed_height) * 0.05
    for asset in derived["assets"]:
        width, height = asset["size"]
        assert width == height, f"{asset['file']} is not square, so the mark was distorted"


def test_the_install_icons_are_opaque_and_the_favicons_are_not_forced(derived: dict) -> None:
    for asset in derived["assets"]:
        with Image.open(BRAND_DIR / asset["file"]) as image:
            alpha_min, _ = image.convert("RGBA").getchannel("A").getextrema()
        if asset["opaque"]:
            assert alpha_min == 255, f"{asset['file']} should be opaque for platform installs"
        else:
            assert alpha_min < 255, f"{asset['file']} unexpectedly lost its transparency"


def test_the_provenance_files_are_not_shipped_to_browsers() -> None:
    """The original and the derivation record belong in Git, not in every visitor's payload.

    `public/` is copied verbatim into the build, so keeping the 610 KB original there meant serving
    it to everyone. This pins the split: served icons in `public/brand/`, provenance in
    `brand-source/`.
    """
    assert (PROVENANCE / SOURCE_NAME).is_file()
    assert DERIVED.is_file()
    assert not (BRAND_DIR / SOURCE_NAME).exists(), "the owner's original is being served"
    assert not (BRAND_DIR / "derived-manifest.json").exists()


def test_the_brand_source_declares_the_same_assets_as_the_derivation(derived: dict) -> None:
    """The single source of truth and the files must agree, in both directions.

    The nav mark is declared as `logoPath` and the install/document icons as `icons`, so the icon
    list is compared against the derived set *minus* the mark — my first version compared them
    directly and reported the mark as missing from a list it was never meant to be in.
    """
    text = BRAND_TS.read_text(encoding="utf-8")
    declared = set(re.findall(r'src:\s*"(/brand/[a-z0-9\-\.]+\.png)"', text))
    mark = re.search(r'logoPath:\s*"(/brand/[^"]+)"', text)
    assert mark is not None, "the brand source no longer declares a logo path"
    on_disk = {f"/brand/{asset['file']}" for asset in derived["assets"]}
    expected = on_disk - {mark.group(1)}
    assert declared == expected, f"declared {sorted(declared)} but derived {sorted(expected)}"

    assert (REPO / "apps" / "web" / "public" / mark.group(1).lstrip("/")).is_file()
    assert 'logoStatus: "FINAL"' in text, "the brand source does not claim the final artwork"
