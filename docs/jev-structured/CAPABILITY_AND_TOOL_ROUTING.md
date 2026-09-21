# Capability routing and tool-intent checking (modules E and F)

Two new deterministic-first layers in `app/jev/`:

* **Module E — `capability_router.py`** routes a learner request to one of
  CourseMate's **own** teaching capabilities (`direct_qa`, `node_lesson`, …).
* **Module F — `tool_intent.py`** guards model-proposed, side-effecting tool calls
  so a semantic "intent" signal can never become a permission or a write.

Both use the two catalog definitions that already exist in
`decision_catalog.json` — `teaching.capability.v1` and `tool.intent.v1` (both
Choice). No new definition is invented, and nothing else in the catalog is touched.

All defaults stay `shadow` like the other definitions; a Jev suggestion is recorded
in `jev_decision_receipts` only, and the deterministic fallback is what the business
uses until a definition is individually promoted to `on`. There is no live Jev call
anywhere — only the offline `FakeTransport` has run.

---

## Module E — `TeachingCapabilityRouter`

### Capability catalog (in code, `CAPABILITY_CATALOG`)

Nine entries, one per existing CourseMate capability. Each entry carries
`skill_id`, `version`, `description`, `allowed_modes` (product modes), `preconditions`
(permission tags + state requirements), `required_inputs` (what the handler needs),
`writes_data`, `cost_class`, `forbidden_conditions`, and the existing
handler/orchestrator entry point it maps to.

| skill_id | existing handler entry point | writes_data | cost_class | preconditions (gating) | forbidden when |
|---|---|---|---|---|---|
| `direct_qa` | `app.services.qa.QaService.stream` | no | read | — | an assessment is active |
| `node_lesson` | `app.learning.orchestrator.LearningOrchestrator.teach` | yes | write | `permission:teach`, `pair_bound` | an assessment is active |
| `prerequisite_explanation` | `app.learning.knowledge.KnowledgeService.select_repair_prerequisite` | no | read | `permission:teach` | an assessment is active |
| `worked_example` | `app.jev.callsites.select_pedagogy_method` → `WORKED_EXAMPLE` | no | generate | `permission:teach` | Thinking-only; an assessment is active |
| `code_trace` | `app.jev.callsites.select_pedagogy_method` → `TRACE` | no | generate | `permission:teach` | Thinking-only; an assessment is active |
| `figure_explanation` | `app.ui_extension.domain.V3DomainAdapter` figure/attachment explanation path | no | generate | — | an assessment is active |
| `exercise` | `app.cm_update.app.generate_exercise_run` | yes | write | `permission:exercise`, `pair_bound` | an assessment is active |
| `step_explanation` | `app.cm_update.app` step-explanation endpoints (`cmui_step_explanations`) | yes | write | `revealed` (answer already revealed) | the answer is still unrevealed |
| `assessment_submission` | `app.learning.orchestrator.LearningOrchestrator.submit_assessment` | yes | write | `permission:assess`, `active_assessment` | no assessment is active |

Notes on faithfulness:

* `direct_qa` and `node_lesson` are the two answer/teach entry points; both are
  written off during an active assessment (the assessment flow has its own assist
  surface) so they can never leak a hidden answer.
* `worked_example` and `code_trace` are **Thinking-only**: a `normal` request can
  never be routed to them (see the filter stage below).
* `step_explanation` is the hidden-answer capability: it is excluded while the answer
  is unrevealed.
* `assessment_submission` is legal only inside an active assessment and still
  requires the confirmed UI action (the backend `submit_assessment` owns the write).

### Stage 1 — deterministic code filters (zero Jev calls)

`filter_candidates(request, catalog)` prunes the nine capabilities to the *survivors*
that are legal for this request. Checks, in order:

1. **server candidate hint** — `candidate_skills` (the `teaching.capability.v1`
   required-state field) narrows the universe; empty means "no pre-narrowing";
2. **enabled entry points** — a disabled entry point is never re-enabled;
3. **product mode** — `request.product_mode` must be in the capability's
   `allowed_modes`;
4. **normal vs Thinking** — a `thinking_only` capability is excluded when the request
   is `normal`;
5. **revealed answer** — `answer_unrevealed` (and the `revealed` precondition) excludes
   hidden-answer capabilities while the answer is unrevealed;
6. **active assessment** — `assessment_active` forbids teaching/QA during an
   assessment, and `assessment_inactive`/`active_assessment` gates the submission
   capability;
7. **permissions** — every `permission:<tag>` precondition must be held by the actor.

The explicit user command is handled **before** these filters and with zero Jev calls:
when the caller has already resolved the message with
`app.learning.intent_commands.route_explicit_command` and passes the resulting action
as `explicit_command`, the router maps it deterministically
(`QUIZ_WAIT`→`exercise`, `SUBMIT_ASSESSMENT`→`assessment_submission`,
`ANSWER_ONLY`→`direct_qa`, `CONTINUE`/`ANSWER_AND_RESUME`→`node_lesson`) and still runs
the mapped capability through the filters, so an explicit command can never override a
hard invariant (`PAUSE`/`OTHER` are not capabilities and fall through to the normal
path).

### Stage 2 — Jev selection (short list, at most one disambiguation round)

Only the survivors are offered to `teaching.capability.v1`. The offered list is
capped at `MAX_OFFERED_CANDIDATES = 4` (catalog order), so the full nine-template set
is never sent and only the selected candidate's detail object is looked up from the
in-code catalog. The gateway validates the choice against the offered criteria, and
the router re-checks the id before acting, so an illegal candidate proposed by the
transport is rejected, never routed. If the first answer is ambiguous (`NO_SKILL` or an
invalid response) and more than one candidate was offered, exactly **one**
disambiguation round is allowed (`MAX_DISAMBIGUATION_ROUNDS = 1`); after that, or on
`NO_SKILL`/unavailable, the router returns the current legal default (`direct_qa`
unless overridden).

### Result is usable by the caller

`TeachingCapabilityRouter.resolve(request, *, owner_user_id, authorization_scope, course_id=..., ...)`
returns a `CapabilityResolution` with `skill_id`, the selected `Capability` object,
its `handler` name and the recorded `path`
(`deterministic:explicit_command` | `jev` | `jev:disambiguated` | `fallback:<reason>`),
plus `used_jev`, `receipt_id`, the `offered_candidates`, `disambiguation_rounds` and
`jev_calls`. The business layer calls the existing orchestrator entry named in
`handler` — a receipt alone is not integration.

### Production wiring (one-line insertion, owning workstream)

The router is wired where the teaching shell / `cm_update` decides which capability
to serve a learner message:

```python
# app/cm_update/app.py (or the teaching shell) — after route_explicit_command returns None:
from app.jev.capability_router import CapabilityRequest, TeachingCapabilityRouter

router = TeachingCapabilityRouter(jev)
choice = router.resolve(
    CapabilityRequest(
        learner_request=message,
        product_mode=product_mode,
        revealed_state=revealed,
        active_assessment=active_assessment,
        pair_binding=pair_id,
        candidate_skills=server_candidate_skills,
        mode=mode,                       # "normal" | "thinking"
        permissions=actor_permissions,
        explicit_command=route_explicit_command(message),
    ),
    owner_user_id=user_id,               # server-derived, never client-supplied
    authorization_scope="capability",
    course_id=course_id,
    workspace_id=workspace_id,
    material_revision=material_revision,
)
# dispatch to choice.handler (the existing entry point) — the deterministic backend
# still owns permissions, the exact locator, arithmetic, state machines, budgets,
# coverage, marks and every write.
```

`product_mode`, `permissions`, `pair_binding`, `active_assessment` and
`revealed_state` are server-derived; none are client-supplied. The cache scope
(`owner_scope_hash`, `course_id`, …) is built inside `resolve` from the
server-derived `owner_user_id`/`authorization_scope`/course/workspace values, so a
Jev call always writes a properly-scoped receipt and never reuses another owner's
cached judgement.

---

## Module F — `ToolIntentCheck`

Only for **model-proposed, side-effecting** tool calls where the user's real intent
is semantically ambiguous. The order is fixed and nothing may skip it:

1. **schema + permission checks (code)** — a pure read returns `ALLOW` immediately; an
   explicitly legitimate action (deterministic button + schema-validated + permission
   already held) returns `ALLOW` with zero Jev calls and no new approval dialog; a
   required permission the actor does not hold returns `REFUSE_UNAUTHORIZED` in code
   before Jev is ever reached.
2. **optional Jev intent check** — only for the remaining model-proposed
   side-effecting calls, over the four `tool.intent.v1` required fields
   (`user_message`, `proposed_tool`, `tool_arguments`, `actor_scope`). The user's own
   message is the only authorization signal: instructions found inside documents or
   tool output are never forwarded as authorization.
3. **re-check permission and object revision immediately before execution** — if the
   permission is now missing or the object revision changed since the intent check,
   the stale judgement is discarded (`REFUSE_UNAUTHORIZED` / `REFUSE_STALE`).
4. **the original tool executes** — only on `ALLOW`; the guard itself never executes
   the tool and never writes business state.

Hard rules:

* a `CONSISTENT` verdict is an *intent signal only*, never an authorization — it can
  never grant a permission the actor did not already hold;
* `INCONSISTENT_WITH_INTENT` / `AMBIGUOUS` / unavailable always return
  `REQUIRE_CONFIRMATION` for the side effect — never auto-allow, and plain chat never
  fails (only the write is held, the caller still answers the message);
* a user merely asking about a deadline cannot produce a Task write (the write is
  blocked pending confirmation);
* the highest reasoning tier does not regain a dollar-risk gate: the permission and
  revision re-checks run unconditionally for every side-effecting call.

`ToolIntentCheck.authorize(...)` returns a `ToolIntentResult` (`ALLOW` |
`REQUIRE_CONFIRMATION` | `REFUSE_UNAUTHORIZED` | `REFUSE_STALE`) with `used_jev`,
`jev_label`, `receipt_id`, `path` and `jev_calls`. `needs_intent_check(...)` is the
tier-independent predicate (`not is_read_only and not explicit`).

### Production wiring (one-line insertion, owning workstream)

Wrap the executor of a model-proposed side-effecting tool call:

```python
from app.jev.tool_intent import ToolIntentCheck

check = ToolIntentCheck(jev)
result = check.authorize(
    user_message=user_message,            # the user's own words only
    proposed_tool=tool_name,
    tool_arguments=tool_arguments,
    actor_scope=actor_scope,
    actor_permissions=actor_permissions,  # server-derived, at proposal time
    required_permissions=required_permissions,
    is_read_only=tool_is_read_only,
    explicit=action_was_explicitly_requested,
    object_revision=object_revision,      # captured before the intent check
    current_revision=current_revision,    # re-read immediately before execution
    owner_user_id=user_id,                # server-derived, never client-supplied
    authorization_scope="tool_intent",
    course_id=course_id,
)
if result.verdict != "ALLOW":
    return require_confirmation_or_refuse(result)   # never execute, never auto-allow
run_original_tool(tool_name, tool_arguments)
```

---

## Requested follow-ups

* **Host wiring (default-off today).** Wire `JevGateway` + `SqlReceiptStore(database)`
  into `app/main.py` / `app/cm_update/integration.py` / `app/ui_extension/mount.py`
  once a TypeSafe credential exists; everything stays `shadow` until calibrated.
* The capability catalog is a faithful, in-code mapping to the existing entry points;
  the owning workstream must confirm the `handler` strings against the exact
  dispatch site before flipping any definition to `on`.
