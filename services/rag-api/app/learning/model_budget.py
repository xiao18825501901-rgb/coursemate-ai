"""One unchanged daily allowance shared by legacy and new generic LLM calls."""

import sqlite3


def daily_model_call_counts(
    connection: sqlite3.Connection, owner_user_id: str, course_id: str
) -> tuple[int, int]:
    row = connection.execute(
        "SELECT COUNT(*) AS user_calls, COALESCE(SUM(course_id=?),0) AS course_calls "
        "FROM (SELECT course_id FROM learning_model_call_reservations "
        "WHERE owner_user_id=? AND created_at>=date('now') "
        "AND status!='BLOCKED' AND quota_scope='INTERACTIVE' "
        "UNION ALL SELECT course_id FROM generic_llm_calls "
        "WHERE owner_user_id=? AND created_at>=date('now') AND status!='BLOCKED')",
        (course_id, owner_user_id, owner_user_id),
    ).fetchone()
    return int(row[0]), int(row[1])
