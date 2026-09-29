"""The isolated SQL oracle's contract.

These tests pin the properties that make the oracle usable as a *deterministic*
check rather than as a second opinion:

* it cannot reach anything outside the private database it is given;
* it cannot run more than one statement, for longer than its budget, or return
  more rows than its bound -- each of those is ``NOT_SUPPORTED``, never a pass;
* its comparison semantics distinguish the cases where SQL answers actually
  differ (bag versus set, ``ORDER BY``, ``LEFT JOIN`` predicate placement,
  ``DISTINCT``, ``NULL``);
* and it states its own scope, so agreement on one instance is never reported as
  equivalence.
"""
from __future__ import annotations

import sqlite3

import pytest

from app.learning.sql_oracle import (
    OracleCheck,
    OracleLimits,
    check_equivalence,
    check_expected_rows,
    required_parameters_are_stated,
    run_statement,
)

SCHEMA = """
CREATE TABLE student(id INTEGER, name TEXT);
CREATE TABLE enrolment(id INTEGER, course TEXT, grade INTEGER);
"""

DATA = """
INSERT INTO student VALUES (1,'ann'),(2,'bob'),(3,'cid');
INSERT INTO enrolment VALUES (1,'db',90),(1,'ai',NULL),(2,'db',70),(2,'db',70),(3,'net',NULL);
"""


# ---------------------------------------------------------------- isolation


def test_a_statement_cannot_reach_outside_its_private_database() -> None:
    for statement in (
        "ATTACH DATABASE '/tmp/other.sqlite3' AS other",
        "PRAGMA user_version = 7",
        "PRAGMA writable_schema = 1",
        "SELECT load_extension('anything')",
    ):
        result = run_statement(statement=statement, schema=SCHEMA, data=DATA)
        assert result.status == "NOT_SUPPORTED", statement


def test_a_statement_cannot_write_or_run_a_second_statement() -> None:
    for statement in (
        "DELETE FROM student",
        "UPDATE student SET name='x'",
        "INSERT INTO student VALUES (9,'z')",
        "CREATE TABLE extra(x)",
        "CREATE TEMP TABLE extra(x)",
        "DROP TABLE student",
        "SELECT 1; DELETE FROM student",
    ):
        result = run_statement(statement=statement, schema=SCHEMA, data=DATA)
        assert result.status == "NOT_SUPPORTED", statement


def test_a_read_only_statement_runs() -> None:
    result = run_statement(
        statement="SELECT name FROM student ORDER BY id", schema=SCHEMA, data=DATA
    )
    assert result.ok
    assert result.rows == (("ann",), ("bob",), ("cid",))


# ------------------------------------------------------------- boundedness


def test_an_over_long_statement_is_not_supported() -> None:
    statement = "SELECT " + " + ".join(["1"] * 5_000)
    result = run_statement(
        statement=statement, schema=SCHEMA, data=DATA, limits=OracleLimits()
    )
    assert result.status == "NOT_SUPPORTED"
    assert result.reason == "ORACLE_STATEMENT_TOO_LONG"


def test_an_oversized_result_is_not_supported_rather_than_truncated() -> None:
    result = run_statement(
        statement="SELECT * FROM enrolment, student, enrolment AS e2",
        schema=SCHEMA,
        data=DATA,
        limits=OracleLimits(max_rows=2),
    )
    assert result.status == "NOT_SUPPORTED"
    assert result.reason == "ORACLE_RESULT_TRUNCATED"


def test_an_empty_statement_is_not_supported() -> None:
    assert run_statement(statement="   ", schema=SCHEMA, data=DATA).status == (
        "NOT_SUPPORTED"
    )


def test_a_fixture_without_tables_is_refused() -> None:
    result = run_statement(statement="SELECT 1", schema="", data="")
    assert result.status == "NOT_SUPPORTED"
    assert result.reason == "ORACLE_FIXTURE_EMPTY"


# -------------------------------------------------------- comparison semantics


def test_distinct_matters_only_under_bag_comparison() -> None:
    """A `DISTINCT` bug is invisible to a set comparison and visible to a bag one."""
    reference = "SELECT id FROM enrolment"
    candidate = "SELECT DISTINCT id FROM enrolment"
    as_set = check_equivalence(
        reference=reference,
        candidate=candidate,
        schema=SCHEMA,
        data=DATA,
        comparison="SET",
    )
    as_bag = check_equivalence(
        reference=reference,
        candidate=candidate,
        schema=SCHEMA,
        data=DATA,
        comparison="BAG",
    )
    assert as_set.status == "PASS"
    assert as_bag.status == "FAIL"
    assert as_bag.comparison == "BAG"


def test_predicate_placement_on_a_left_join_is_detected() -> None:
    """`ON` and `WHERE` are not interchangeable after a LEFT JOIN."""
    result = check_equivalence(
        reference="SELECT student.id FROM student LEFT JOIN enrolment "
        "ON enrolment.id = student.id AND enrolment.course = 'ai'",
        candidate="SELECT student.id FROM student LEFT JOIN enrolment "
        "ON enrolment.id = student.id WHERE enrolment.course = 'ai'",
        schema=SCHEMA,
        data=DATA,
        comparison="ORDERED",
    )
    assert result.status == "FAIL"


def test_row_order_matters_only_under_ordered_comparison() -> None:
    reference = "SELECT id FROM student ORDER BY id"
    candidate = "SELECT id FROM student ORDER BY id DESC"
    ordered = check_equivalence(
        reference=reference,
        candidate=candidate,
        schema=SCHEMA,
        data=DATA,
        comparison="ORDERED",
    )
    unordered = check_equivalence(
        reference=reference,
        candidate=candidate,
        schema=SCHEMA,
        data=DATA,
        comparison="BAG",
    )
    assert ordered.status == "FAIL"
    assert unordered.status == "PASS"


def test_null_equals_null_in_a_result_set() -> None:
    """A result set is a value: two NULLs in a column are the same row value."""
    result = check_equivalence(
        reference="SELECT grade FROM enrolment WHERE grade IS NULL",
        candidate="SELECT grade FROM enrolment WHERE grade IS NULL",
        schema=SCHEMA,
        data=DATA,
        comparison="BAG",
    )
    assert result.status == "PASS"
    # And a NULL is not silently equal to a real value.
    differing = check_equivalence(
        reference="SELECT id, grade FROM enrolment ORDER BY id, grade",
        candidate="SELECT id, coalesce(grade, 0) FROM enrolment ORDER BY id, grade",
        schema=SCHEMA,
        data=DATA,
        comparison="ORDERED",
    )
    assert differing.status == "FAIL"


def test_a_duplicate_row_bug_is_caught_by_the_bag_comparison() -> None:
    """A missing join condition multiplies rows; only the bag comparison sees it."""
    result = check_equivalence(
        reference="SELECT student.name, enrolment.course FROM student "
        "JOIN enrolment ON enrolment.id = student.id",
        candidate="SELECT student.name, enrolment.course FROM student "
        "JOIN enrolment ON 1 = 1",
        schema=SCHEMA,
        data=DATA,
        comparison="BAG",
    )
    assert result.status == "FAIL"


def test_expected_rows_are_compared_with_the_same_semantics() -> None:
    passing = check_expected_rows(
        candidate="SELECT name FROM student WHERE id <= 2",
        schema=SCHEMA,
        data=DATA,
        expected_rows=[["ann"], ["bob"]],
        comparison="BAG",
    )
    failing = check_expected_rows(
        candidate="SELECT name FROM student WHERE id <= 2",
        schema=SCHEMA,
        data=DATA,
        expected_rows=[["ann"], ["cid"]],
        comparison="BAG",
    )
    assert passing.status == "PASS"
    assert failing.status == "FAIL"


def test_a_statement_that_cannot_run_is_not_supported_not_a_pass() -> None:
    result = check_equivalence(
        reference="SELECT id FROM student",
        candidate="SELECT id FROM nonexistent_table",
        schema=SCHEMA,
        data=DATA,
        comparison="SET",
    )
    assert result.status == "NOT_SUPPORTED"
    assert result.comparison is None


# ------------------------------------------------------------------- scope


def test_a_pass_states_its_scope_and_never_claims_equivalence() -> None:
    result = check_equivalence(
        reference="SELECT id FROM student",
        candidate="SELECT id FROM student",
        schema=SCHEMA,
        data=DATA,
        comparison="SET",
    )
    assert result.status == "PASS"
    assert "supplied schema and rows only" in result.scope
    assert "not a proof of equivalence" in result.scope


def test_an_oracle_pass_must_name_its_comparison() -> None:
    with pytest.raises(ValueError):
        OracleCheck(
            check="sql_result_equivalence",
            status="PASS",
            comparison=None,
            detail="compared",
        )


def test_two_statements_that_agree_here_may_differ_on_another_instance() -> None:
    """The oracle's scope is the point, so the counterexample is pinned.

    `grade >= 90` and `grade > 85` agree on the base instance (its only non-null
    grades are 90 and 70) and diverge as soon as a grade of 87 is added.  The
    oracle reports agreement on the first and disagreement on the second, which
    is exactly the whole of what it claims.
    """
    reference = "SELECT id FROM enrolment WHERE grade >= 90"
    candidate = "SELECT id FROM enrolment WHERE grade > 85"
    agreeing = check_equivalence(
        reference=reference,
        candidate=candidate,
        schema=SCHEMA,
        data=DATA,
        comparison="BAG",
    )
    assert agreeing.status == "PASS"
    diverging = check_equivalence(
        reference=reference,
        candidate=candidate,
        schema=SCHEMA,
        data=DATA + "INSERT INTO enrolment VALUES (5,'db',87);",
        comparison="BAG",
    )
    assert diverging.status == "FAIL"


# ------------------------------------------------- declared-parameter check


def test_declared_parameters_present_in_the_stem_pass() -> None:
    result = required_parameters_are_stated(
        stem="Using epsilon = 1.0 and MinPts = 3, list the core points.",
        parameters=["epsilon", "MinPts"],
    )
    assert result.status == "PASS"


def test_a_declared_parameter_missing_from_the_stem_fails() -> None:
    result = required_parameters_are_stated(
        stem="List the core points of the supplied dataset.",
        parameters=["epsilon", "MinPts"],
    )
    assert result.status == "FAIL"
    assert result.failed


def test_no_declared_parameters_is_not_supported_rather_than_a_pass() -> None:
    result = required_parameters_are_stated(stem="List the core points.", parameters=[])
    assert result.status == "NOT_SUPPORTED"


def test_the_oracle_never_returns_the_statement_text() -> None:
    """A diagnostic must not echo private course content into a report."""
    secret = "SELECT name FROM student WHERE name = 'a-very-private-name'"
    result = run_statement(statement=secret, schema=SCHEMA, data=DATA)
    assert result.ok
    assert secret not in (result.reason or "")
    failing = check_equivalence(
        reference="SELECT id FROM student",
        candidate="SELECT id FROM missing_table",
        schema=SCHEMA,
        data=DATA,
        comparison="SET",
    )
    assert "missing_table" not in failing.detail
