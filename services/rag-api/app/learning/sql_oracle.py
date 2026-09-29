"""An isolated, bounded SQL oracle for the deterministic Question Engine check.

The Question Engine already has six hard gates, but none of them can *execute*
anything: they prove identity, marks, source scope, conditions, question shape
and blind-solve currency.  A question whose answer is a query result therefore had
no deterministic check at all, which is the gap this module closes.

Three properties matter more than coverage, and each is enforced here rather than
promised:

**Isolation.**  Every statement runs in a private in-memory SQLite database
created for that call, against caller-supplied schema and rows only.  An
authorizer denies anything that is not a read of that database -- ``ATTACH``,
``PRAGMA`` writes, ``load_extension``, temp-table creation and every write verb
are refused, so no statement can reach a file, a socket or another database.
This is not a sandbox against a hostile author; it is a sandbox against an
accidental one, which is what a model-written query is.

**Boundedness.**  A statement is length-capped, its row count is capped, and a
progress handler aborts it after a wall-clock budget.  Exceeding any bound is a
``NOT_SUPPORTED`` result, never a pass.

**Declared scope.**  The oracle answers one question only: *do these two
statements agree on this schema and this data?*  It never generalises to
"equivalent on any database", and :class:`Equivalence` says so in its own type.
Agreement on the supplied instance is evidence about the supplied instance; a
different instance may separate the two statements, and no amount of sample
agreement upgrades that.

The comparison semantics are explicit because they are where SQL answers actually
differ:

* ``ORDER BY`` in the question turns the comparison into an ordered list
  comparison, because the row order is part of the answer;
* without it, the comparison is a **bag** comparison when duplicates are possible
  and a **set** comparison otherwise, as the question's contract requires;
* ``NULL`` compares equal to ``NULL`` for these purposes -- a result set is a
  value, and two rows that are both NULL in a column are the same row value;
* column names are compared only when the contract asks for them.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from typing import Annotated, Any, Final, Literal

from pydantic import Field, StringConstraints, model_validator

from app.learning.models import Contract

# Bounds.  They are deliberately small: this oracle exists to check a course
# exercise, not to be a query service.
MAX_STATEMENT_CHARS: Final = 8_000
MAX_ROWS: Final = 5_000
MAX_COLUMNS: Final = 64
MAX_RESULT_CELLS: Final = 200_000
DEFAULT_TIME_BUDGET_SECONDS: Final = 2.0
MAX_SEED_ROWS: Final = 5_000

OracleStatus = Literal["AGREE", "DIFFER", "NOT_SUPPORTED"]
RowComparison = Literal["ORDERED", "BAG", "SET"]

# SQLite action codes that a read-only statement may perform.
_ALLOWED_ACTIONS: Final = frozenset(
    {
        getattr(sqlite3, name)
        for name in (
            "SQLITE_SELECT",
            "SQLITE_READ",
            "SQLITE_FUNCTION",
        )
        if hasattr(sqlite3, name)
    }
)


class OracleError(RuntimeError):
    """A stable refusal from the oracle; never carries the statement text."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


@dataclass(frozen=True)
class OracleLimits:
    max_statement_chars: int = MAX_STATEMENT_CHARS
    max_rows: int = MAX_ROWS
    max_columns: int = MAX_COLUMNS
    max_result_cells: int = MAX_RESULT_CELLS
    time_budget_seconds: float = DEFAULT_TIME_BUDGET_SECONDS
    max_seed_rows: int = MAX_SEED_ROWS


@dataclass(frozen=True)
class OracleResult:
    """One statement's execution outcome, with its scope stated in the type."""

    status: Literal["OK", "NOT_SUPPORTED"]
    columns: tuple[str, ...] = ()
    rows: tuple[tuple[Any, ...], ...] = ()
    row_count: int = 0
    truncated: bool = False
    reason: str | None = None
    elapsed_ms: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status == "OK"


class OracleCheck(Contract):
    """The recorded outcome of one oracle check on one question revision."""

    check: ShortText
    status: Literal["PASS", "FAIL", "NOT_SUPPORTED"]
    method: Literal["ROW_COMPARISON", "DECLARED_PARAMETER_PRESENCE"] | None = None
    comparison: RowComparison | None = None
    detail: ShortText
    scope: ShortText = "supplied schema and rows only; not a proof of equivalence"

    @model_validator(mode="after")
    def a_pass_names_the_method_that_decided_it(self) -> OracleCheck:
        if self.status == "PASS" and self.method is None:
            raise ValueError("an oracle PASS must name the method that decided it")
        if self.method == "ROW_COMPARISON" and self.status == "PASS" and (
            self.comparison is None
        ):
            raise ValueError("a row-comparison PASS must name its comparison")
        return self

    @property
    def failed(self) -> bool:
        return self.status == "FAIL"


def _authorizer(action: int) -> int:
    return sqlite3.SQLITE_OK if action in _ALLOWED_ACTIONS else sqlite3.SQLITE_DENY


def _private_database(limits: OracleLimits) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.set_authorizer(lambda action, *_args: _authorizer(action))
    deadline = time.perf_counter() + limits.time_budget_seconds

    def _budget() -> int:
        return 1 if time.perf_counter() > deadline else 0

    connection.set_progress_handler(_budget, 10_000)
    return connection


def seed(
    connection: sqlite3.Connection,
    *,
    schema: str,
    data: str,
    limits: OracleLimits,
) -> None:
    """Create the tables and insert the rows the question declares.

    Seeding runs with the authorizer temporarily removed, because creating the
    fixture is the host's job, not the statement's.  It is then restored before
    any author statement is prepared.
    """
    if len(schema) > limits.max_statement_chars or len(data) > limits.max_statement_chars:
        raise OracleError("ORACLE_FIXTURE_TOO_LARGE", "The oracle fixture exceeds the bound.")
    connection.set_authorizer(None)
    try:
        connection.executescript(schema)
        rows = connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
        if int(rows.fetchone()[0]) == 0:
            raise OracleError("ORACLE_FIXTURE_EMPTY", "The oracle fixture defines no tables.")
        connection.executescript(data)
    except sqlite3.Error as error:
        raise OracleError("ORACLE_FIXTURE_INVALID", "The oracle fixture could not be loaded.") from error
    finally:
        connection.set_authorizer(lambda action, *_args: _authorizer(action))


def run_statement(
    *,
    statement: str,
    schema: str,
    data: str,
    limits: OracleLimits | None = None,
) -> OracleResult:
    """Execute one read-only statement in a private, bounded database."""
    limits = limits or OracleLimits()
    if not statement.strip():
        return OracleResult(status="NOT_SUPPORTED", reason="ORACLE_STATEMENT_EMPTY")
    if len(statement) > limits.max_statement_chars:
        return OracleResult(status="NOT_SUPPORTED", reason="ORACLE_STATEMENT_TOO_LONG")
    started = time.perf_counter()
    connection: sqlite3.Connection | None = None
    try:
        connection = _private_database(limits)
        seed(connection, schema=schema, data=data, limits=limits)
        # A second statement cannot be smuggled in: only one statement is
        # prepared, and SQLite rejects trailing content.
        cursor = connection.execute(statement)
        description = cursor.description or ()
        if len(description) > limits.max_columns:
            return OracleResult(status="NOT_SUPPORTED", reason="ORACLE_TOO_MANY_COLUMNS")
        columns = tuple(str(item[0]) for item in description)
        rows: list[tuple[Any, ...]] = []
        truncated = False
        for index, row in enumerate(cursor):
            if index >= limits.max_rows:
                truncated = True
                break
            if (index + 1) * max(len(columns), 1) > limits.max_result_cells:
                truncated = True
                break
            rows.append(tuple(row))
        if truncated:
            return OracleResult(
                status="NOT_SUPPORTED",
                reason="ORACLE_RESULT_TRUNCATED",
                elapsed_ms=(time.perf_counter() - started) * 1000,
            )
        return OracleResult(
            status="OK",
            columns=columns,
            rows=tuple(rows),
            row_count=len(rows),
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )
    except sqlite3.Error as error:
        return OracleResult(
            status="NOT_SUPPORTED",
            reason=f"ORACLE_{type(error).__name__.upper()}",
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )
    except OracleError as error:
        return OracleResult(
            status="NOT_SUPPORTED",
            reason=error.code,
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )
    finally:
        if connection is not None:
            connection.close()


def _canonical_row(row: tuple[Any, ...]) -> tuple[Any, ...]:
    """A comparison key in which NULL equals NULL and floats are normalised."""
    canonical: list[Any] = []
    for value in row:
        if value is None:
            canonical.append(("\x00NULL",))
        elif isinstance(value, bool):
            canonical.append(("bool", int(value)))
        elif isinstance(value, float):
            canonical.append(("num", round(value, 9)))
        elif isinstance(value, int):
            canonical.append(("num", round(float(value), 9)))
        elif isinstance(value, bytes):
            canonical.append(("blob", value.hex()))
        else:
            canonical.append(("text", str(value)))
    return tuple(canonical)


def compare_results(
    left: OracleResult, right: OracleResult, *, comparison: RowComparison
) -> tuple[bool, str]:
    """Compare two executed results under the declared comparison semantics."""
    if comparison == "ORDERED":
        same = tuple(_canonical_row(row) for row in left.rows) == tuple(
            _canonical_row(row) for row in right.rows
        )
        return same, "ordered row sequences compared"
    if comparison == "SET":
        same = set(map(_canonical_row, left.rows)) == set(map(_canonical_row, right.rows))
        return same, "row sets compared (duplicates ignored)"
    # BAG: duplicates matter, but the order of the rows does not.
    import collections

    same = collections.Counter(map(_canonical_row, left.rows)) == collections.Counter(
        map(_canonical_row, right.rows)
    )
    return same, "row bags compared (duplicates counted, order ignored)"


def check_equivalence(
    *,
    reference: str,
    candidate: str,
    schema: str,
    data: str,
    comparison: RowComparison,
    check: str = "sql_result_equivalence",
    limits: OracleLimits | None = None,
) -> OracleCheck:
    """Compare a candidate statement against a reference on one instance.

    The returned check is scoped: ``PASS`` means "these agree on the supplied
    schema and rows", never "these are equivalent".
    """
    left = run_statement(statement=reference, schema=schema, data=data, limits=limits)
    right = run_statement(statement=candidate, schema=schema, data=data, limits=limits)
    if not left.ok:
        return OracleCheck(
            check=check,
            status="NOT_SUPPORTED",
            method="ROW_COMPARISON",
            comparison=None,
            detail=f"the reference statement could not be executed ({left.reason})",
        )
    if not right.ok:
        return OracleCheck(
            check=check,
            status="NOT_SUPPORTED",
            method="ROW_COMPARISON",
            comparison=None,
            detail=f"the candidate statement could not be executed ({right.reason})",
        )
    same, how = compare_results(left, right, comparison=comparison)
    return OracleCheck(
        check=check,
        status="PASS" if same else "FAIL",
        method="ROW_COMPARISON",
        comparison=comparison,
        detail=(
            f"{how}; {left.row_count} reference row(s) against {right.row_count} "
            f"candidate row(s) on the supplied schema and rows"
        ),
    )


def check_expected_rows(
    *,
    candidate: str,
    schema: str,
    data: str,
    expected_rows: list[list[Any]],
    comparison: RowComparison,
    check: str = "sql_expected_rows",
    limits: OracleLimits | None = None,
) -> OracleCheck:
    """Compare a candidate statement against a literal expected result."""
    result = run_statement(statement=candidate, schema=schema, data=data, limits=limits)
    if not result.ok:
        return OracleCheck(
            check=check,
            status="NOT_SUPPORTED",
            method="ROW_COMPARISON",
            comparison=None,
            detail=f"the candidate statement could not be executed ({result.reason})",
        )
    expected = OracleResult(
        status="OK",
        columns=result.columns,
        rows=tuple(tuple(row) for row in expected_rows),
        row_count=len(expected_rows),
    )
    same, how = compare_results(result, expected, comparison=comparison)
    return OracleCheck(
        check=check,
        status="PASS" if same else "FAIL",
        method="ROW_COMPARISON",
        comparison=comparison,
        detail=(
            f"{how}; {result.row_count} row(s) returned against "
            f"{len(expected_rows)} expected on the supplied schema and rows"
        ),
    )


def required_parameters_are_stated(*, stem: str, parameters: list[str]) -> OracleCheck:
    """A narrow, executable under-specification check.

    When a question declares the parameters its answer depends on, the oracle can
    settle the one thing the reviewers could not agree on: is each parameter
    actually present in the stem?  This is deliberately limited to declared
    parameters -- it is not a general under-specification judge, and it returns
    ``NOT_SUPPORTED`` when nothing was declared.
    """
    if not parameters:
        return OracleCheck(
            check="declared_parameters_stated",
            status="NOT_SUPPORTED",
            method="DECLARED_PARAMETER_PRESENCE",
            comparison=None,
            detail="no parameters were declared for this question",
        )
    missing = [name for name in parameters if name.strip() and name.strip() not in stem]
    if missing:
        return OracleCheck(
            check="declared_parameters_stated",
            status="FAIL",
            method="DECLARED_PARAMETER_PRESENCE",
            comparison=None,
            detail=f"{len(missing)} declared parameter(s) do not appear in the stem",
        )
    return OracleCheck(
        check="declared_parameters_stated",
        status="PASS",
        method="DECLARED_PARAMETER_PRESENCE",
        comparison=None,
        detail=f"all {len(parameters)} declared parameter(s) appear in the stem",
    )
