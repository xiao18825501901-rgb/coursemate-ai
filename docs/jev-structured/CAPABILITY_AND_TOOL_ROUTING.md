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

### Production wiring — **LANDED** (this round)

The router is wired into the teaching run endpoint, and its result is *consumed*
rather than recorded: `app/cm_update/app.py::run_capability` is the single entry
point, called from the `POST /conversations/{conv_id}/runs` route right after
`route_explicit_command`:

```python
capability, capability_skill, teaching_flow = run_capability(
    jev,
    text=data.text,
    explicit_action=explicit_action,          # deterministic router, 0 Jev
    node_bound=bool(data.node_id),
    pair_binding=str(run_pair['id']) if run_pair is not None else None,
    teaching_mode=teaching_mode,
    owner_user_id=user['id'],                 # server-derived, never client-supplied
    course_id=conv['course'],
)
```

What `run_capability` guarantees, so that a Jev answer can never break the product:

* **only the capabilities this endpoint actually serves are ever offered.** A
  node-bound run offers `node_lesson / worked_example / code_trace /
  prerequisite_explanation`; a non-node run offers `direct_qa /
  figure_explanation`. A capability whose handler lives in another endpoint
  (`exercise`, `step_explanation`, `assessment_submission`) is never offered and
  is additionally rejected by a code-owned backstop if a transport names it.
* **the code-owned baseline is the flow the shell already took**: `node_lesson`
  for a node-bound run, `direct_qa` otherwise, and `direct_qa` when the learner's
  own explicit command was "answer only" (`ANSWER_ONLY`).
* **the result is dispatched**: `teaching_flow = skill_id in TEACHING_FLOW_SKILLS`
  decides whether the run binds the V3 learning journey through the orchestrator
  (`remote('knowledge.begin_learning')` → `LearningOrchestrator`, plus the
  `cmui_node_starts` claim and the `cmui_learning` LEARNING row) or answers
  without advancing the lesson. Under shadow/off the baseline is returned, so
  every one of those branches is exactly what it was before.
* **an explicit command costs zero Jev calls** and is never overridden by the
  semantic layer (`CONTINUE`/`ANSWER_AND_RESUME` → teaching flow,
  `ANSWER_ONLY` → answer-only, both proven with a receipt count of 0).
* **the decision is observable**: the create-run response carries
  `capability: {skill_id, teaching_flow, used_jev, path, explicit_command}`.

Not (yet) dispatched: the heterogeneous handler strings in `CAPABILITY_CATALOG`
(`QaService.stream`, `LearningOrchestrator.teach`, `generate_exercise_run`, the
step-explanation endpoints). Those surfaces have their own product endpoints, so
this run endpoint deliberately offers only the two flows it implements. Flipping
`teaching.capability.v1` to `on` therefore changes *which* teaching skill serves
the request and whether the lesson advances — never permissions, reasoning
strength, revealed answers, Pairs or node bindings.


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

### Production wiring — **LANDED** (this round), opt-in and default-off

The real execution boundary for a model-proposed tool call is the Node task agent
(`services/agent-api`), not the Python service, so the guard runs there and calls
the Python guard over an authenticated internal hop:

```
AgentService.chat ──▶ ToolExecutor.execute(owner, tool, args, {userMessage})
                        └─ write tool only ──▶ JevToolIntentGate.checkToolIntent
                                                 └─ POST /api/jev/tool-intent
                                                      └─ ToolIntentCheck.authorize
```

* `services/rag-api/app/api/tool_intent.py` — `POST /api/jev/tool-intent`, guarded
  by a constant-time internal-token comparison (`JEV_TOOL_INTENT_TOKEN`,
  `X-CourseMate-Internal-Token`). A missing/blank configured token disables the
  endpoint (503) instead of opening it; a mismatch is 401. The body is bounded
  (message/tool/permission/revision lengths and a serialized `tool_arguments`
  cap), the shared `app.state.jev_service` is reused, and the route writes nothing
  except the Jev receipt the guard itself records.
* `services/agent-api/src/tools/intent-gate.ts` — `JevToolIntentGate` with an
  injected `fetchImpl` and a bounded timeout (default 1500 ms). Network error,
  timeout, non-2xx, malformed JSON or an unrecognised verdict all map to
  `REQUIRE_CONFIRMATION` / `intent:unavailable`; the gate never throws.
* `services/agent-api/src/tools/executor.ts` — only the four write tools
  (`createTask`, `updateTask`, `completeTask`, `deleteTask`) are gated;
  `searchTask` is read-only and is never gated. Permissions are computed in code
  (`["tasks:write"]` for the authenticated owner), never supplied by the model.

Three modes, so the guard can be introduced without changing production behaviour:

| `JEV_TOOL_INTENT_MODE` | HTTP call | effect | default |
|---|---|---|---|
| `off` | none at all | the existing synchronous path, byte-identical (no gate object is even constructed) | **yes** |
| `advisory` | yes | the verdict is recorded on the tool result (`intent`) and the tool still executes | no |
| `enforce` | yes | a non-`ALLOW` verdict blocks the write (`CONFIRMATION_REQUIRED` / `INTENT_REFUSED`) and the tool does not run | no |

`enforce` requires both `JEV_TOOL_INTENT_URL` (absolute http/https, no credentials,
no control characters) and a non-empty `JEV_TOOL_INTENT_TOKEN`; config validation
throws at load time otherwise. `README`-level operator note: with `off` (the
default) no new environment variable is required and no call is made.


---

## Follow-ups

* **Host wiring — DONE.** One shared `SemanticDecisionService`
  (`app/main.py::create_app` → `application.state.jev_service`) is threaded through
  `app/ui_extension/mount.py` → `app/cm_update/integration.py` →
  `app/cm_update/app.py::create_app(jev=…)` → `V3DomainAdapter(jev=…)`, and reused
  by the feedback and tool-intent routes. With no TypeSafe credential the live
  transport fails typed and everything stays `shadow`.
* **Still to do before any `on`:** live Jev validation and calibration on the
  labelled test split, then the module ablation. Every definition is `shadow`
  today and no quality claim is made for any of them.
* The capability catalog is a faithful, in-code mapping to the existing entry
  points, but only the two flows this run endpoint implements are offered to the
  router; the remaining `handler` strings name their own endpoints and would need
  a real dispatch site before they could be selected.

## Module F in the shipped product (added round 90)

Module F had unit coverage (`intent-gate`, `executor-intent-gate`, `test_api_tool_intent.py`) but no
end-to-end evidence that a *write* was refused. It now has two journeys, and they are deliberately
run as two configurations of the same deployment because they make opposite claims about one guard:

| Configuration | Journey | Assertion |
|---|---|---|
| `JEV_TOOL_INTENT_MODE=enforce`, `JEV_TOOL_INTENT_URL` intentionally unreachable, no credential | "a write whose intent check cannot answer is not executed" | the proposed `createTask` is refused with `CONFIRMATION_REQUIRED`; the guard's own record is `{path: "fallback:unavailable", verdict: "REQUIRE_CONFIRMATION", jevCalls: 0}`; and the task board is byte-identical before and after |
| `enforce`, reachable endpoint, live credential, `tool.intent.v1=on`, raised timeout | "an explicit, authorised write is not over-blocked once its intent is established" | the same message creates the task (`ok: true`, a real task id) |

The first journey is stated against an unreachable endpoint rather than the real one on purpose.
Its first version pointed at the real endpoint and still got `fallback:unavailable` — not because
the guard said no, but because the live decision took **1.35 s against the guard's 1.5 s default**.
That would have made the journey pass or fail with the model's mood, so the configuration is now the
claim, and the finding is recorded in `JEV_SECURITY_AND_FAILURE_MODES.md` §8a: fail-closed is
correct, but an `enforce` deployment should raise `JEV_TOOL_INTENT_TIMEOUT_MS` (the explicit-write
journey requires ≥5 s) or it will occasionally ask a learner to confirm what they already said
unambiguously.

Neither journey routes through the web shell: the agent's only tool surface is
`POST /api/agent/chat`, whose body is `{message}` — a caller cannot name a tool or its arguments — so
these are HTTP journeys against the real agent and the real RAG endpoint, not UI journeys. That is a
property of the product, not a shortcut.

