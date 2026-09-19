"""Reconcile crashed-worker runs and their current explanation projection atomically."""


def reclaim_and_reconcile(db, *, now_epoch, lease_grace_seconds, updated_at):
    """No generation or retries. A live lease and a newer explanation run are untouched."""
    if lease_grace_seconds <= 0:
        raise ValueError('Lease grace must be positive')
    cutoff = float(now_epoch) - float(lease_grace_seconds)
    with db.connect(True) as connection:
        reclaimed = connection.execute(
            "UPDATE cmui_runs SET status='failed',error='SERVER_RESTARTED',updated_at=? "
            "WHERE status IN ('queued','planning','generating') "
            "AND (lease_heartbeat IS NULL OR CAST(lease_heartbeat AS REAL)<?)",
            (updated_at, cutoff),
        ).rowcount
        reconciled = connection.execute(
            "UPDATE cmui_step_explanations SET "
            "status=(SELECT status FROM cmui_runs WHERE cmui_runs.id=cmui_step_explanations.run), "
            "updated_at=? WHERE status='generating' AND EXISTS("
            "SELECT 1 FROM cmui_runs WHERE cmui_runs.id=cmui_step_explanations.run "
            "AND cmui_runs.owner=cmui_step_explanations.owner "
            "AND cmui_runs.status IN ('completed','failed','cancelled'))",
            (updated_at,),
        ).rowcount
    return {'reclaimed_runs': reclaimed, 'reconciled_explanations': reconciled}
