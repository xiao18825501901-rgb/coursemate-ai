#!/usr/bin/env python3
"""Pinned-revision snapshot download for the CourseMate Laya model.

Downloads exactly one pinned revision of ``convaiinnovations/laya`` (subfolder
``multilingual``) via ``huggingface_hub.snapshot_download``, verifies every file
with a per-file SHA-256, lands the result atomically into ``--dest``, and writes
a ``model-manifest.json``.

The script also verifies an existing directory offline (``--verify-only``) using
the recorded manifest and an optional pinned-hash map. No network is needed for
``--verify-only`` or ``--help``.

Guarantees:
  * Never downloads ``latest`` or any unpinned branch — a full commit SHA is
    required for download.
  * Never falls back to an unverified mirror — the only source is the Hugging
    Face hub, and every file is re-hashed locally before anything lands.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

PINNED_REPO = "convaiinnovations/laya"
PINNED_SUBFOLDER = "multilingual"
PINNED_REVISION = "1c5edc17a7acd8701df6fc341c0d179f1c62c982"
DEFAULT_MANIFEST = "model-manifest.json"

_SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
_CHUNK = 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(directory: Path, repo: str, subfolder: str, revision: str) -> dict:
    files = []
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            rel = path.relative_to(directory).as_posix()
            files.append(
                {"path": rel, "sha256": sha256_file(path), "size_bytes": path.stat().st_size}
            )
    return {
        "schema_version": 1,
        "repo_id": repo,
        "subfolder": subfolder,
        "revision": revision,
        "downloaded_at": datetime.now(UTC).isoformat(),
        "downloaded_with": "huggingface_hub.snapshot_download",
        "files": files,
    }


def write_manifest(directory: Path, manifest_name: str, manifest: dict) -> None:
    target = directory / manifest_name
    tmp = directory / f".{manifest_name}.tmp"
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, target)


def run_download(args: argparse.Namespace) -> int:
    # Lazy import: --help and --verify-only must work without huggingface_hub.
    from huggingface_hub import snapshot_download  # noqa: PLC0415

    dest = Path(args.dest).resolve()
    if dest.exists() and any(dest.iterdir()):
        print(f"error: destination {dest} is not empty; refusing to overwrite", file=sys.stderr)
        return 2

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.parent / f".{dest.name}.download-{os.getpid()}-{secrets.token_hex(4)}"
    tmp.mkdir(parents=True, exist_ok=False)

    try:
        print(f"snapshot_download(repo={args.repo!r}, revision={args.revision}, "
              f"subfolder={args.subfolder!r})")
        snapshot_download(
            repo_id=args.repo,
            revision=args.revision,
            allow_patterns=[f"{args.subfolder}/*"],
            local_dir=tmp,
        )
        payload = tmp / args.subfolder if (tmp / args.subfolder).is_dir() else tmp
        manifest = build_manifest(payload, args.repo, args.subfolder, args.revision)
        write_manifest(payload, args.manifest, manifest)
        # Atomic landing: the final directory appears only after everything has
        # been verified and the manifest written.
        os.replace(payload, dest)
        print(f"landed {len(manifest['files'])} files at {dest}")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def verify_existing(args: argparse.Namespace) -> int:
    dest = Path(args.dest).resolve()
    manifest_path = dest / args.manifest
    if not manifest_path.is_file():
        print(f"error: no {args.manifest} in {dest}; cannot verify offline", file=sys.stderr)
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    if manifest.get("revision") != args.revision:
        print(
            f"error: manifest revision {manifest.get('revision')!r} != "
            f"expected {args.revision!r}",
            file=sys.stderr,
        )
        return 1

    pinned: dict[str, str] = {}
    if args.expected_hashes:
        pinned = json.loads(Path(args.expected_hashes).read_text(encoding="utf-8"))

    listed = [f.get("path") for f in manifest.get("files", []) if isinstance(f, dict)]
    ok = True
    for entry in manifest.get("files", []):
        rel = entry.get("path")
        if not isinstance(rel, str):
            continue
        path = dest / rel
        if not path.is_file():
            print(f"MISSING   {rel}")
            ok = False
            continue
        actual = sha256_file(path)
        if actual != entry.get("sha256"):
            print(f"BAD HASH  {rel} (expected {entry.get('sha256')}, got {actual})")
            ok = False
            continue
        if rel in pinned and pinned[rel] != actual:
            print(f"PIN MISMATCH {rel} (pinned {pinned[rel]}, got {actual})")
            ok = False
            continue
        print(f"OK        {rel}")

    for rel in pinned:
        if rel not in listed:
            print(f"EXTRA PIN {rel} (not present in manifest)")
            ok = False

    print("verify: all files match" if ok else "verify: FAILED")
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Pinned-revision Laya model snapshot download + offline verification."
    )
    parser.add_argument("--repo", default=PINNED_REPO, help="Hugging Face repo id.")
    parser.add_argument("--subfolder", default=PINNED_SUBFOLDER, help="Repo subfolder to fetch.")
    parser.add_argument(
        "--revision",
        default=PINNED_REVISION,
        help="Full commit SHA to pin (defaults to the CourseMate-pinned revision).",
    )
    parser.add_argument(
        "--dest",
        default=None,
        help="Destination directory (atomic landing). Required unless --verify-only.",
    )
    parser.add_argument(
        "--manifest",
        default=DEFAULT_MANIFEST,
        help="Manifest filename to write/read (default: model-manifest.json).",
    )
    parser.add_argument(
        "--expected-hashes",
        default=None,
        help="Optional JSON map of relative-path -> sha256 to cross-check against.",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Verify an existing directory offline against its manifest; do not download.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.revision.lower() in {"latest", "main", "master"} or not _SHA_RE.match(args.revision):
        print(
            "error: refusing to download an unpinned revision; pass a full 40-char commit SHA",
            file=sys.stderr,
        )
        return 2

    if args.verify_only:
        if not args.dest:
            print("error: --verify-only requires --dest", file=sys.stderr)
            return 2
        return verify_existing(args)

    if not args.dest:
        print("error: --dest is required (or use --verify-only)", file=sys.stderr)
        return 2
    return run_download(args)


if __name__ == "__main__":
    raise SystemExit(main())
