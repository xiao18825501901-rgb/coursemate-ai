# JEV_APPLICATION_DECISION_MATRIX

How the 12 Jev decisions are applied inside CourseMate, what authority each one has, what
happens when Jev is unavailable, and what is actually enabled today. Everything in this matrix
comes from the implemented code and its tests — not from the design intent alone.

Implemented layer: `services/rag-api/app/jev/` (`catalog.py`, `decision_catalog.json`,
`gateway.py`, `service.py`, `receipt_store.py`, `errors.py`, `models.py`) plus migration
`028_jev_decision_receipts.sql`. Official source verification for this session:
`typesafe-sdk` **0.7.0** (MIT) — client `TypeSafeClient(model="jev").system_one(state, questions)`
with `Choice(instructions, criteria=…)`, `Score(instructions, criteria=[…])`, `Noul(instructions)`;
response accessors `.choices[k].choice`, `.scores[k].score`, `.nouls[k].noul` (0..1);
credential `TYPESAFE_API_KEY` read server-side only. **UNKNOWN and therefore not relied upon**:
the exact meaning of a returned `Score` value (level key vs index vs description) — the validator
accepts all three forms and records what it saw. No endpoint, model id, timeout or payload field
was invented.

## 1. Authority rules (enforced by code + tests)

| Rule | Enforcement |
|---|---|
| Jev never authors content | the gateway only accepts the primitives Choice/Noul/Score; there is no free-text channel |
| Choice may only select ids the server supplied | an unknown/illegal candidate id from the transport is rejected and never becomes a user-visible choice (`test_jev_gateway`) |
| Noul/Score are signals, never grades or permissions | `probability_is_grade=False`; no call site converts them into marks, LEARNED, access or budgets |
| Jev cannot write state | all call sites treat the signal as advisory; a failed call leaves learning state, coverage and grades untouched (`test_jev_wiring` no-state-write test) |
| Deterministic code keeps authority | permissions, transactions, sums, ids, official grades and completion stay in the existing services |
| Cache honours scope + invalidation | cached judgements are keyed by authorization scope/course/workspace/material revision/node+spec/question hash/input hash/model version; a material-revision change or another owner scope never reuses an entry (tests cover both) |
| Failure is safe | typed outcomes `JEV_UNKNOWN`/`JEV_TIMEOUT`/`JEV_UNAVAILABLE`/`JEV_INVALID_RESPONSE`/`JEV_NOT_CONFIGURED`; every call site falls back to its deterministic path |

## 2. The 12 decisions

| # | Decision key | Primitive | Applied to (CourseMate feature) | Server-provided candidates | Deterministic fallback | Mode today |
|---|---|---|---|---|---|---|
| 1 | `retrieval.support.v1` | Score | evidence usefulness after the global fusion in `V3DomainAdapter._retrieve` | fused candidate ids within the authorized scopes | the fused ranking itself (RRF) | **shadow** |
| 2 | `source.supports_claim.v1` | Noul | citation-support check for a claim/answer span | the exact source spans that were cited | claim stays unverified (no support claimed) | shadow (helper, no live call site) |
| 3 | `source.select_span.v1` | Choice | choose which supplied span supports a claim | server-generated span ids only | keep the real selected evidence or return no support | shadow (helper) |
| 4 | `context.keep_segment.v1` | Noul | optional-history trimming for the prompt | bounded optional history segments (never anchors, originals, constraints or unresolved errors) | keep fixed anchors + bounded recent originals | shadow (helper; selector is the only place allowed to drop old segments) |
| 5 | `intent.next_action.v1` | Choice | routing an ambiguous follow-up (CONTINUE / ANSWER_ONLY / ANSWER_AND_RESUME / REPAIR_PREREQUISITE / QUIZ_WAIT / SUBMIT_ASSESSMENT / PAUSE / OTHER) | the state's legal actions | explicit UI actions and commands are handled by deterministic rules; otherwise the current deterministic mode | shadow (helper) |
| 6 | `pedagogy.next_method.v1` | Choice | presentation strategy (worked example / trace / definition / counterexample / compare / continue) | template-provided strategy set | versioned template default | shadow (helper) |
| 7 | `coverage.item_support.v1` | Choice | REQUIRED-item support signal recorded in the delivery provenance during `_submit_delivery` | saved teaching text + the frozen spec item + real spans | coverage stays **pending**; the existing reviewer/hash validation decides | **shadow** |
| 8 | `assessment.criterion_review.v1` | Choice | rubric-criterion cross-check (SATISFIED / PARTIAL / NOT_SATISFIED / NEEDS_REVIEW) | frozen question + frozen criterion + reference solution + student answer | existing grader / deterministic evaluation; unresolved → NEEDS_REVIEW, never 0 because a tool failed | shadow (helper; grading loop call site not enabled) |
| 9 | `template.match.v1` | Choice | course template classification (01–14 or OTHER) | the registry ids | evidence-based DeepSeek classification, else OTHER | shadow (helper) |
| 10 | `exercise.prototype.v1` | Choice | choosing an authorized exercise prototype | server-filtered prototype ids | deterministic nearest qualified prototype / clearly-labelled diagnostic question | shadow (helper) |
| 11 | `graph.prerequisite.v1` | Choice | prerequisite-repair candidate selection | current-course authorized graph nodes | published prerequisite order without semantic expansion | shadow (helper) |
| 12 | `corpus.quality.v1` | Score | offline material/parse-quality screening | document fragments + parse flags | keep the original; mark parse limitations for ingestion review | shadow (helper) |

## 3. What is enabled, and why nothing is `on` yet

* Every definition is **shadow**: the deterministic result is what the user sees, and the Jev
  suggestion is recorded in a receipt.
* Thresholds are deliberately `UNSET_UNTIL_CALIBRATED_ON_LABELLED_DATA`; the catalog states
  `probability_is_grade=false` and `gold_source` must be independent evidence/human labels, not
  model self-scores. Without credentials there is no labelled run, so switching anything to `on`
  would be an uncalibrated claim — the plan explicitly forbids that.
* Wiring that is live in shadow: retrieval re-rank (may only reorder already-authorized
  candidates and may never displace an exact-target hit) and coverage item-support (recorded in
  provenance only). Intent/context/assessment helpers exist and are tested but have no live `on`
  call site yet.

## 4. Evidence in this round

| Evidence | Result |
|---|---|
| `pytest tests/test_jev_catalog.py tests/test_jev_gateway.py tests/test_jev_service.py tests/test_jev_wiring.py tests/test_jev_deepseek_gap_regressions.py -q` | 27 passed |
| Catalog integrity (12 keys, primitives split, thresholds unset) | covered by `test_jev_catalog` |
| Invalid candidate id rejected; timeout/unavailable typed; no retry | covered by `test_jev_gateway` |
| Cache hit/miss, material-revision invalidation, cross-user isolation | covered by `test_jev_service` |
| Shadow mode is byte-identical for the user; exact-target slot preserved | covered by `test_jev_wiring` |
| Live TypeSafe call | **NOT_RUN** — no credentials; `SdkTransport` raises `JEV_NOT_CONFIGURED` |
| A/B/C/D ablation on labelled data | **NOT_RUN** — plan's 200 judgements / 40 trajectories / 30 image cases are a plan, not a result |

## 5. Ecosystem decisions

The 20-item ecosystem table (which patterns are adopted, where, and why the rest are not
installed as production dependencies) is recorded in
`docs/jev-deepseek/JEV_SKILL_DECISIONS.md`, produced with this layer. No new runtime dependency
was added: the SDK is imported lazily only inside `SdkTransport`.
