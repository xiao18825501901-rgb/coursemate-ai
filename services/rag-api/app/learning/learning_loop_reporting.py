"""Read-only, privacy-minimised projections over authoritative loop ledgers."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from app.db import Database
from app.learning.learning_loop import LearningLoopService


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone-aware event time required")
    return parsed.astimezone(UTC)


def current_observation(database: Database, *, as_of: datetime | None = None) -> dict[str, Any]:
    """Return current operational facts without answers, prompts or identity labels."""

    observed_at = (as_of or datetime.now(UTC)).astimezone(UTC)
    loop = LearningLoopService(database)
    with database.connect() as connection:
        cycles = connection.execute(
            "SELECT id,owner_user_id,course_id,objective_id,internal,started_at,completed_at "
            "FROM learning_loop_cycles ORDER BY started_at,id"
        ).fetchall()
        reliability = connection.execute(
            "SELECT fact.*,COALESCE(cycle.internal,actor.internal,0) AS internal "
            "FROM learning_loop_reliability_facts AS fact "
            "LEFT JOIN learning_loop_cycles AS cycle ON cycle.id=fact.cycle_id "
            "LEFT JOIN learning_loop_actor_classifications AS actor "
            "ON actor.owner_user_id=fact.owner_user_id ORDER BY fact.created_at,fact.id"
        ).fetchall()
        model = connection.execute(
            "SELECT role,status,COUNT(*) AS calls,SUM(input_tokens) AS input_tokens,"
            "SUM(output_tokens) AS output_tokens FROM learning_model_run_evidence "
            "GROUP BY role,status ORDER BY role,status"
        ).fetchall()

    cards: list[tuple[Any, dict[str, Any]]] = []
    internal_excluded = 0
    invalid_excluded = 0
    for cycle in cycles:
        if cycle["internal"]:
            internal_excluded += 1
            continue
        if cycle["completed_at"] is None:
            continue
        card = loop.evidence_card(owner_user_id=str(cycle["owner_user_id"]), cycle_id=str(cycle["id"]))
        if not card["currently_valid_closure"]:
            invalid_excluded += 1
            continue
        cards.append((cycle, card))

    goal_weeks: set[tuple[str, str, str, int, int]] = set()
    week_users: dict[str, set[str]] = defaultdict(set)
    week_counts: dict[str, int] = defaultdict(int)
    correct = graded = 0
    by_owner: dict[str, list[datetime]] = defaultdict(list)
    for cycle, card in cards:
        completed = _time(str(cycle["completed_at"]))
        if completed > observed_at:
            raise ValueError("future completion is not a valid metric fact")
        year, week, _ = completed.isocalendar()
        key = (str(cycle["owner_user_id"]), str(cycle["course_id"]),
               str(cycle["objective_id"]), year, week)
        if key not in goal_weeks:
            goal_weeks.add(key)
            label = f"{year}-W{week:02d}"
            week_counts[label] += 1
            week_users[label].add(str(cycle["owner_user_id"]))
        final = card["attempts"][-1] if card["attempts"] else None
        if final and final["outcome"] in {"CORRECT", "PARTIAL", "INCORRECT"}:
            graded += 1
            correct += int(final["outcome"] == "CORRECT")
        by_owner[str(cycle["owner_user_id"])].append(completed)

    mature = returned = 0
    for values in by_owner.values():
        values.sort()
        anchor = values[0]
        if observed_at < anchor + timedelta(days=9):
            continue
        mature += 1
        returned += int(any(anchor + timedelta(days=6) <= value < anchor + timedelta(days=9)
                            for value in values[1:]))

    stage_projection: dict[str, dict[str, Any]] = {}
    for row in reliability:
        if row["internal"]:
            continue
        stage = str(row["stage"])
        group = stage_projection.setdefault(stage, {
            "started": set(), "SUCCEEDED": 0, "FAILED": 0, "CANCELLED": 0,
            "UNKNOWN": 0, "IN_FLIGHT": 0, "latencies_ms": [],
        })
        group["started"].add(str(row["operation_id"]))
        status = str(row["status"])
        if status != "STARTED":
            group[status] += 1
        if status == "SUCCEEDED" and row["latency_ms"] is not None:
            group["latencies_ms"].append(int(row["latency_ms"]))
    reliability_public: dict[str, Any] = {}
    for stage, group in stage_projection.items():
        latencies = sorted(group.pop("latencies_ms"))
        started = len(group.pop("started"))
        reliability_public[stage] = {
            "denominator_started": started,
            **group,
            "success_fraction_started": group["SUCCEEDED"] / started if started else None,
            "latency_sample_n": len(latencies),
            "p50_success_latency_ms": latencies[(len(latencies) - 1) // 2] if latencies else None,
            "pending_and_unknown_not_counted_as_success": True,
        }

    return {
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        "status": "CURRENT_OBSERVATION_NOT_STUDENT_UPLIFT",
        "weekly_cycles": {
            "unique_users": len(by_owner),
            "user_goal_week_closures": len(goal_weeks),
            "by_iso_week_goal_closures": dict(week_counts),
            "by_iso_week_unique_users": {key: len(value) for key, value in week_users.items()},
            "correctness": {"correct": correct, "graded": graded,
                            "rate": correct / graded if graded else None},
            "internal_cycles_excluded": internal_excluded,
            "currently_invalid_cycles_excluded": invalid_excluded,
        },
        "d7_return": {"numerator": returned, "denominator": mature,
                      "rate": returned / mature if mature else None,
                      "window": "[anchor+6d,anchor+9d)", "maturity": "9 elapsed days"},
        "activation_24h": {"status": "UNKNOWN_SIGNUP_AUTHORITY_NOT_CONNECTED"},
        "reliability": reliability_public,
        "model_usage": [dict(row) for row in model],
        "cost": {"currency_totals": None, "status": "UNKNOWN_NO_BILLING_AMOUNT_LEDGER",
                 "token_usage_is_not_a_bill": True},
        "revenue": {"value": None, "status": "NOT_CONNECTED"},
        "student_validation": {"status": "NOT_YET_MATURE", "claim": None},
        "contains_raw_answers": False,
    }
