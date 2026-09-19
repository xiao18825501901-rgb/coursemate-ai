# Independent Pair lifecycle regressions

Scope: R08 explicit unified-history association, first-node teaching, and R13 explanation cancellation. Tests run against the mounted real V3 application and DomainPort using synthetic isolated databases, verified synthetic primary actor, and `CMUI_AUTO_VERIFY_NEW_USERS=false`. No external model, identity, or production request occurs.

`services/rag-api/tests/test_codex_pair_lifecycle.py`: **4 failed, 2 dependency warnings, 11.47 seconds** (exit 1).

| Regression | Observed evidence | Source cause |
|---|---|---|
| Legacy per-lane creations must not silently combine unrelated histories | Creating unrelated teach and problem conversations without explicit Pair produces one combined Pair instead of two single-sided histories. | `cm_update/app.py:new_conversation` selects newest Pair whose lane is empty. |
| Explicit `pair_id` targets the requested older Pair; repeat cannot overwrite its lane | Request rejected 422 with `extra_forbidden` for `pair_id`. The later overwrite-protection assertion awaits implementing this contract. | `cm_update/models.py:ConversationCreate` lacks `pair_id`; `new_conversation` has no explicit lookup. |
| UI-style pre-bind followed by first node teaching automatically uses Thinking once | Valid node/spec, successful `/pairs/{id}/bind`, accepted run; persisted `cmui_runs.teaching_mode` is `normal` instead of `thinking`. | `new_run` forces Thinking only while changing a NULL binding; pre-bind consumed the only condition without starting teaching. |
| Cancel a silent explanation and restore a terminal window state | Cancel returns 200; underlying run becomes `cancelled`, but GET explanation still returns `generating`. | `generate_explanation_run` cancellation and `explanation_cancel` update run state but not explanation state. |

The cancellation reproduction substitutes a controlled silent async provider at the model boundary, confirms entry with a thread event, requests cancellation through the real route, and checks persisted GET state. It does not depend on a paid timeout. It reproduces same-process cancellation bookkeeping; cross-process watchdog behavior remains a separate assertion.

The first-node test also defines replay and later normal-follow-up assertions. Those are not claimed passed in the RED run because the first-mode assertion fails first. Similarly, the explicit Pair test does not claim a currently reproduced overwrite: current implementation rejects the new explicit-pair field before that assertion can execute.

```powershell
$env:CMUI_ALLOW_BILLABLE='false'
$env:CMUI_PROVIDER_MODE='test'
$env:CMUI_ENV='test'
$env:CMUI_AUTO_VERIFY_NEW_USERS='false'
$env:CMUI_DATA_DIR=''
$env:PYTHONPATH='services/rag-api'
& 'work/codex-audit/venv/Scripts/python.exe' -m pytest services/rag-api/tests/test_codex_pair_lifecycle.py -q --basetemp=work/codex-audit/pair-lifecycle-temp
```

Only this test file and findings document were added by this bounded review; no application source was edited.
