"""Explicit eligibility setup for legacy tests of authorized campus workflows.

Never autouse: campus negative tests retain their unverified actors. Every
caller names exactly the synthetic subjects required by its original test.

Callers and intended eligibility:
- bridge trace, coverage, integration, learning closure, legacy history: user-a
  owns the campus learning data; user-b is another eligible campus user whose
  private-resource access must still fail independently of the campus gate.
- single worker, test provider, tree/dual mode: only user-a performs authorized
  campus learning. Other synthetic identities are not granted by these fixtures.
- task agent: only user-a needs the selected campus course for forwarding; task
  isolation itself grants no campus qualification to other actors.

The helper is deliberately absent from current-change/code-audit campus gate
tests. Assertions and production authorization are unchanged.
"""
from app.cm_update.auth import ensure_user
from app.cm_update.social import set_verified


def authorize_synthetic_campus_users(client, *subjects):
    ui = client.app.state.ui_extension_app
    assert client.app.state.settings.app_env == 'test'
    assert not ui.state.cfg.auto_verify_new_users
    for subject in subjects:
        assert subject in {'user-a', 'user-b'}, 'Only declared synthetic test actors may be granted'
        ensure_user(ui.state.db, subject, auto_verify=False)
        set_verified(ui.state.db, subject, 'admin', 'Explicit isolated authorized-campus test actor')
