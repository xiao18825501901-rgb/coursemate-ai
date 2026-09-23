"""Offline, read-only diagnostic: which qualification origins an existing UI
database actually holds.

`campus_qualification_policy` has two supported values. `registered_active` is
the default and the only value that ever existed: any verified qualification row
opens campus content, including the historical `method='registered'` rows the
registration auto-grant wrote before it was removed. `verified_only` also
requires the row to prove its origin (`code`/`admin`/`grandfathered`).

The owner needs one aggregate number before switching: `registration_auto` is
exactly how many accounts a switch to `verified_only` would newly refuse. This
program prints that count and the two others, and nothing else.

It never prints a subject id, a display name or a verification code, and it
opens the database read-only (`mode=ro`) with `PRAGMA query_only=ON`, so a
diagnosis can never repair, rewrite or downgrade the rows whose provenance it is
measuring — the historical `registered` rows in particular. Opening a
write-ahead-logging database read-only may still create a zero-byte `-wal` and a
`-shm` companion next to it (SQLite needs the shared-memory file for readers);
the database file itself is not modified, which is checked with a hash in the
migration note that ships with this diagnostic.

A UI database captured before campus qualification existed has no
`cmui_verification` table. It reports zero real and zero registration-auto rows
and every account as unqualified, and says so on stderr rather than looking
broken.

Usage:
    python -m app.cm_update.qualification_origin_report --database <ui.sqlite3>
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path

from app.brand import BRAND

from .social import qualification_origin_counts


class _ReadOnlyDatabase:
    """The read surface `qualification_origin_counts` needs, over a `mode=ro` URI.

    A deliberate stand-in for `db.Database` rather than the real class:
    `Database.connect()` opens read-write, which can create `-wal`/`-shm`
    siblings next to a database the operator only wants a count from. `write=True`
    is refused outright so a later caller cannot quietly turn this diagnostic
    into a migration.
    """

    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self, write: bool = False):
        if write:
            raise ValueError('The qualification origin report is read-only')
        connection = sqlite3.connect(
            self.path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5
        )
        connection.row_factory = sqlite3.Row
        try:
            connection.execute('PRAGMA query_only=ON')
            yield connection
        finally:
            connection.close()

    def all(self, sql, args=()):
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(sql, args)]

    def one(self, sql, args=()):
        with self.connect() as connection:
            row = connection.execute(sql, args).fetchone()
            return dict(row) if row else None


def qualification_table_present(database: Path) -> bool:
    """Whether an existing UI database has the qualification table at all.

    A UI database captured before the campus-qualification feature existed has
    `cmui_users` but no `cmui_verification`, and there is nothing in it to
    classify. Checked separately so `origin_report` can stay a pure read and so
    `main` can explain the zeroes it prints instead of implying the database is
    unusable.
    """
    tables = {
        row['name']
        for row in _ReadOnlyDatabase(database).all(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if 'cmui_users' not in tables:
        raise ValueError(f"Target is not a {BRAND.name} UI database: {database}")
    return 'cmui_verification' in tables


def origin_report(database: Path) -> dict[str, int]:
    """The three origin counts for an existing UI database, plus their total.

    `total` is the number of accounts considered: every `cmui_users` row, plus
    any qualification row whose owner is missing from that table. Aggregate
    integers only. A UI database that predates `cmui_verification` reports three
    honest zeroes except `none`, which is then every account it has, because none
    of them can hold a qualification. Raises FileNotFoundError for a missing
    database and ValueError for a file that is not a UI database; it never
    creates either.
    """
    if not database.is_file():
        raise FileNotFoundError(f"Existing UI database is required: {database}")
    read_only = _ReadOnlyDatabase(database)
    try:
        if not qualification_table_present(database):
            users = read_only.one('SELECT COUNT(*) AS accounts FROM cmui_users')['accounts']
            return {'real': 0, 'registration_auto': 0, 'none': users, 'total': users}
        counts = qualification_origin_counts(read_only)
    except sqlite3.Error as error:
        raise ValueError(
            f"Target is not a {BRAND.name} UI database: {error}"
        ) from error
    return {**counts, 'total': sum(counts.values())}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Print campus qualification origin counts (read-only, aggregate only)'
    )
    parser.add_argument('--database', type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    report = origin_report(args.database)
    if not qualification_table_present(args.database):
        # Zeroes are correct but would look like a bug; say why on stderr so the
        # JSON on stdout stays exactly the three counts.
        print(
            f"{BRAND.name} UI database has no cmui_verification table "
            "(it predates campus qualification), so it records no qualified "
            f"account and all {report['none']} of its accounts are unqualified.",
            file=sys.stderr,
        )
    print(json.dumps(report, sort_keys=True, separators=(',', ':')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
