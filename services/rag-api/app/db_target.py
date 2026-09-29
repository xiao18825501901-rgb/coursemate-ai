"""Explicit, verified database targets -- the copy guard.

The incident this module exists for was not "somebody passed the wrong path".  A
helper sourced the deployment environment, a component then read
RAG_DATABASE_PATH *implicitly*, and a migration intended for a restored copy ran
against the live file.  The guard that followed only compared the environment path
with --database and refused when the two disagreed.

That rule is insufficient in both directions:

* **Two equal production paths are not safe.**  If both the environment and the
  argument name production then "they agree", and the migration runs on
  production.  Agreement is not authorisation, so a target that *is* production is
  refused whatever the environment says.
* **String comparison is not identity.**  A symlink, a hard link, a Windows
  junction, a case alias or a ".." walk can name the production file while
  comparing unequal as text, and equal as text while naming a different file.

So a target must be *constructed*, not inferred: the caller states the purpose,
the absolute path, the allowed work root, the known production paths, the expected
schema and the fingerprint of the file this copy was taken from, and every one of
those facts is checked here.  A refusal is a typed code naming the fact that caused
it; nothing is guessed and no default is applied.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

Purpose = Literal[
    "READ_ONLY_PROBE",
    "WRITABLE_REHEARSAL",
    "MIGRATION_REHEARSAL",
    "QUALIFICATION_RUN",
    "PRODUCTION_WRITE",
]

WRITABLE_PURPOSES: Final[frozenset[str]] = frozenset(
    {
        "WRITABLE_REHEARSAL",
        "MIGRATION_REHEARSAL",
        "QUALIFICATION_RUN",
        "PRODUCTION_WRITE",
    }
)
EXPLICIT_ONLY_PURPOSES: Final[frozenset[str]] = frozenset(
    {"READ_ONLY_PROBE", "WRITABLE_REHEARSAL", "MIGRATION_REHEARSAL", "QUALIFICATION_RUN"}
)


class DatabaseTargetError(RuntimeError):
    """A database target was refused, with the exact fact that caused it."""

    def __init__(self, code: str, message: str, **detail: Any) -> None:
        super().__init__(message)
        self.code = code
        self.detail: dict[str, Any] = detail

    def as_dict(self) -> dict[str, Any]:
        return {"status": "REFUSED", "code": self.code, "message": str(self), **self.detail}


def _sha256_file(path: Path, *, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _canonical(path: str | Path) -> str:
    """The comparison form: absolute, realpath-resolved, case-folded on Windows."""
    return os.path.normcase(os.path.realpath(os.path.abspath(str(path))))


def _same_file(left: Path, right: Path) -> tuple[bool, str]:
    """Identity by realpath, then by samefile, then by (st_dev, st_ino)."""
    if _canonical(left) == _canonical(right):
        return True, "realpath"
    try:
        if left.exists() and right.exists() and os.path.samefile(left, right):
            return True, "samefile"
    except OSError:
        pass
    try:
        a = left.stat()
        b = right.stat()
        if a.st_ino and b.st_ino and a.st_ino == b.st_ino and a.st_dev == b.st_dev:
            return True, "inode"
    except OSError:
        pass
    return False, "none"


def _contains(root: Path, candidate: Path) -> bool:
    root_text = _canonical(root)
    candidate_text = _canonical(candidate)
    if candidate_text == root_text:
        return False
    try:
        return os.path.commonpath([root_text, candidate_text]) == root_text
    except ValueError:
        # Different drives on Windows can never be contained.
        return False


def _symlink_component(path: Path) -> str | None:
    """The first component of *path* that is a symbolic link, if any."""
    parts = path.parts[1:] if path.anchor else path.parts
    current = Path(path.anchor) if path.anchor else Path()
    for part in parts:
        current = current / part
        try:
            if current.is_symlink():
                return str(current)
        except OSError:
            return None
    return None


@dataclass(frozen=True)
class DatabaseTarget:
    """A database path positively established to be what it claims to be.

    identity is a digest of the whole descriptor, so a receipt can name the exact
    copy a run used rather than a path that may later mean something else.
    """

    purpose: str
    path: Path
    declared_path: Path
    allowed_root: Path
    production_paths: tuple[Path, ...]
    expected_schema: int | None
    source_fingerprint: str | None
    observed_fingerprint: str | None
    writable_by_process: bool
    production_alias_check: str

    @property
    def identity(self) -> str:
        payload = {
            "purpose": self.purpose,
            "path": _canonical(self.path),
            "allowed_root": _canonical(self.allowed_root),
            "production_paths": sorted(_canonical(p) for p in self.production_paths),
            "expected_schema": self.expected_schema,
            "source_fingerprint": self.source_fingerprint,
            "observed_fingerprint": self.observed_fingerprint,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def as_receipt(self) -> dict[str, Any]:
        return {
            "purpose": self.purpose,
            "declared_path": str(self.declared_path),
            "resolved_path": str(self.path),
            "allowed_root": str(self.allowed_root),
            "production_paths": [str(p) for p in self.production_paths],
            "expected_schema": self.expected_schema,
            "source_fingerprint": self.source_fingerprint,
            "observed_fingerprint": self.observed_fingerprint,
            "production_alias_check": self.production_alias_check,
            "writable_by_process": self.writable_by_process,
            "target_identity": self.identity,
        }


def resolve_database_target(
    *,
    purpose: Purpose,
    explicit_path: str | Path | None,
    allowed_root: str | Path,
    production_paths: Iterable[str | Path] = (),
    environment_path: str | Path | None = None,
    expected_schema: int | None = None,
    source_path: str | Path | None = None,
    require_source_fingerprint: bool = False,
    verify_schema: bool = True,
    require_existing: bool = True,
    require_no_write_permission: bool = False,
    acknowledge_unlisted_production: bool = False,
) -> DatabaseTarget:
    """Establish that *explicit_path* is a legitimate target for *purpose*.

    Refusal is total: the first failing fact ends the call with a typed code.
    """
    productions = tuple(Path(str(item)) for item in production_paths)

    # 0. A writable target without a declared production path cannot be checked
    #    against anything, so the absence is itself a refusal.
    if purpose in WRITABLE_PURPOSES and not productions and not acknowledge_unlisted_production:
        raise DatabaseTargetError(
            "DATABASE_TARGET_PRODUCTION_PATHS_REQUIRED",
            "A writable purpose must declare the production database paths it is "
            "checked against.",
            purpose=purpose,
        )

    # 1. A target is stated, never defaulted.
    if explicit_path is None or str(explicit_path).strip() == "":
        raise DatabaseTargetError(
            "DATABASE_TARGET_NOT_EXPLICIT",
            "No database was named; this purpose never falls back to a default.",
            purpose=purpose,
        )
    declared = Path(str(explicit_path)).expanduser()
    if not declared.is_absolute():
        declared = declared.absolute()
    if ".." in declared.parts:
        raise DatabaseTargetError(
            "DATABASE_TARGET_NOT_EXPLICIT",
            "A target may not be reached by walking up the tree.",
            purpose=purpose,
            declared_path=str(declared),
        )

    # 2. The environment and the argument must not disagree -- and agreeing on
    #    production is still refused below, so this is a consistency check only.
    if environment_path is not None and str(environment_path).strip() != "":
        declared_env = Path(str(environment_path)).expanduser()
        if _canonical(declared_env) != _canonical(declared):
            raise DatabaseTargetError(
                "DATABASE_TARGET_ENVIRONMENT_MISMATCH",
                "The environment and the named target are different files; a "
                "component could read the implicit one.",
                purpose=purpose,
                declared_path=str(declared),
                environment_path=str(declared_env),
            )

    # 3. A target that is production is refused, whether or not anything agrees.
    for production in productions:
        same, how = _same_file(declared, production)
        if same:
            raise DatabaseTargetError(
                "DATABASE_TARGET_IS_PRODUCTION",
                "The named target is the production database.",
                purpose=purpose,
                declared_path=str(declared),
                production_path=str(production),
                matched_by=how,
            )

    # 4. Links and aliases are refused before the file is touched.
    link = _symlink_component(declared)
    if link is not None and purpose in WRITABLE_PURPOSES:
        raise DatabaseTargetError(
            "DATABASE_TARGET_SYMLINK",
            "A writable target may not be reached through a symbolic link.",
            purpose=purpose,
            declared_path=str(declared),
            symlink=str(link),
        )

    if require_existing and not declared.exists():
        raise DatabaseTargetError(
            "DATABASE_TARGET_MISSING",
            "The named target does not exist; a diagnostic never creates one.",
            purpose=purpose,
            declared_path=str(declared),
        )

    resolved = Path(os.path.realpath(declared))

    if resolved.exists():
        try:
            links = resolved.stat().st_nlink
        except OSError:
            links = 1
        if links > 1:
            raise DatabaseTargetError(
                "DATABASE_TARGET_HARDLINK",
                "The target has more than one hard link, so it is not a private copy.",
                purpose=purpose,
                declared_path=str(declared),
                hard_links=links,
            )

    # 5. The target must live inside the work root the caller authorised.
    root = Path(str(allowed_root))
    if not root.is_absolute():
        root = root.absolute()
    if not root.is_dir():
        raise DatabaseTargetError(
            "DATABASE_TARGET_ALLOWED_ROOT_MISSING",
            "The authorised work root does not exist as a directory.",
            purpose=purpose,
            allowed_root=str(root),
        )
    if not resolved.exists():
        raise DatabaseTargetError(
            "DATABASE_TARGET_MISSING",
            "The named target does not exist; a diagnostic never creates one.",
            purpose=purpose,
            declared_path=str(declared),
        )
    if not _contains(root, resolved):
        raise DatabaseTargetError(
            "DATABASE_TARGET_OUTSIDE_ALLOWED_ROOT",
            "The target is outside the authorised work root.",
            purpose=purpose,
            declared_path=str(declared),
            resolved_path=str(resolved),
            allowed_root=str(root),
        )
    for production in productions:
        same, how = _same_file(resolved, production)
        if same:
            raise DatabaseTargetError(
                "DATABASE_TARGET_IS_PRODUCTION",
                "The target resolves onto the production database.",
                purpose=purpose,
                resolved_path=str(resolved),
                production_path=str(production),
                matched_by=how,
            )

    # 6. Permission facts are recorded, and a read-only identity can be demanded.
    writable = os.access(resolved, os.W_OK)
    if require_no_write_permission and writable:
        raise DatabaseTargetError(
            "DATABASE_TARGET_WRITABLE_WHEN_READ_ONLY",
            "This purpose requires an identity that cannot write the target.",
            purpose=purpose,
            resolved_path=str(resolved),
        )

    # 7. The copy must be traceable to the file it was taken from.
    observed = _sha256_file(resolved) if resolved.is_file() else None
    fingerprint: str | None = None
    if source_path is not None and str(source_path).strip() != "":
        source = Path(str(source_path))
        same, how = _same_file(resolved, source)
        if same:
            raise DatabaseTargetError(
                "DATABASE_TARGET_IS_SOURCE",
                "The copy and its source are the same file.",
                purpose=purpose,
                resolved_path=str(resolved),
                source_path=str(source),
                matched_by=how,
            )
        if not source.exists():
            raise DatabaseTargetError(
                "DATABASE_TARGET_SOURCE_MISSING",
                "The declared source of this copy does not exist.",
                purpose=purpose,
                source_path=str(source),
            )
        fingerprint = _sha256_file(source)
    elif require_source_fingerprint:
        raise DatabaseTargetError(
            "DATABASE_TARGET_SOURCE_REQUIRED",
            "This purpose requires the fingerprint of the source the copy came from.",
            purpose=purpose,
            resolved_path=str(resolved),
        )

    # 8. The schema must be the one the caller expects, read read-only.
    if verify_schema and expected_schema is not None:
        with read_only_connection(resolved) as connection:
            row = connection.execute(
                "SELECT MAX(version) FROM schema_migrations"
            ).fetchone()
            actual = int(row[0]) if row and row[0] is not None else 0
        if actual != expected_schema:
            raise DatabaseTargetError(
                "DATABASE_TARGET_SCHEMA_MISMATCH",
                "The target schema is not the expected version.",
                purpose=purpose,
                resolved_path=str(resolved),
                expected_schema=expected_schema,
                observed_schema=actual,
            )

    alias_check = "distinct"
    if productions:
        alias_check = "; ".join(f"{p}: {_same_file(resolved, p)[1]}" for p in productions)

    return DatabaseTarget(
        purpose=purpose,
        path=resolved,
        declared_path=declared,
        allowed_root=root,
        production_paths=productions,
        expected_schema=expected_schema,
        source_fingerprint=fingerprint,
        observed_fingerprint=observed,
        writable_by_process=writable,
        production_alias_check=alias_check,
    )


@contextmanager
def read_only_connection(path: str | Path) -> Iterator[sqlite3.Connection]:
    """A genuinely read-only SQLite connection.

    mode=ro is used rather than immutable=1: the live database is in WAL mode and
    a writer may be active, and immutable=1 would tell SQLite to ignore the WAL and
    read a stale, possibly torn, image.
    """
    uri = f"{Path(path).resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA query_only = ON")
        yield connection
    finally:
        connection.close()


class ReadOnlyDatabase:
    """A probe handle that can read and can never migrate.

    It exposes the subset of app.db.Database a read-only diagnostic needs, and
    every operation that could change the file raises instead of running.
    initialize() is present precisely so that calling it fails loudly rather than
    being an AttributeError a caller might paper over.
    """

    def __init__(self, target: DatabaseTarget) -> None:
        if target.purpose != "READ_ONLY_PROBE":
            raise DatabaseTargetError(
                "DATABASE_TARGET_PURPOSE",
                "ReadOnlyDatabase requires a READ_ONLY_PROBE target.",
                purpose=target.purpose,
            )
        self.target = target
        self.path = target.path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        with read_only_connection(self.path) as connection:
            yield connection

    def initialize(self) -> None:
        raise DatabaseTargetError(
            "DATABASE_TARGET_READ_ONLY",
            "A read-only probe never migrates the database it reads.",
            resolved_path=str(self.path),
        )

    def execute(self, sql: str, parameters: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return list(connection.execute(sql, parameters))

    def scalar(self, sql: str, parameters: tuple[Any, ...] = ()) -> Any:
        rows = self.execute(sql, parameters)
        return rows[0][0] if rows else None


def target_from_environment(**arguments: Any) -> DatabaseTarget:
    """Resolve a target while comparing it with the process's own environment.

    Reading the variable here rather than in the caller is deliberate: the whole
    point is that a component may read it implicitly, so the guard must see the
    same value the component would.
    """
    variable = arguments.pop("environment_variable", "RAG_DATABASE_PATH")
    arguments.setdefault("environment_path", os.environ.get(variable))
    return resolve_database_target(**arguments)


def describe_permissions(path: str | Path) -> dict[str, Any]:
    """The observed permission facts of a path, for a diagnostic receipt."""
    resolved = Path(os.path.realpath(str(path)))
    facts: dict[str, Any] = {"resolved_path": str(resolved), "exists": resolved.exists()}
    if not resolved.exists():
        return facts
    info = resolved.stat()
    facts.update(
        {
            "mode": oct(stat.S_IMODE(info.st_mode)),
            "uid": getattr(info, "st_uid", None),
            "gid": getattr(info, "st_gid", None),
            "st_nlink": info.st_nlink,
            "writable_by_process": os.access(resolved, os.W_OK),
            "readable_by_process": os.access(resolved, os.R_OK),
        }
    )
    return facts
