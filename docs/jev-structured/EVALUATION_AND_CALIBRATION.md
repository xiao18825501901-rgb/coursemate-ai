# EVALUATION_AND_CALIBRATION

How the Jev layer and the six structured-enhancement modules are measured, and what may and may not
be concluded from each kind of run.

**Current state: `ABLATION = RAN LIVE, and the quality gate does not pass`.** The sentence that used to
stand here said "no TypeSafe credential and no DeepSeek key exist in this environment, so no live and
no labelled run has happened" — true when written, false since round 84. What is now measured, on the
47-sample calibration split with a live DeepSeek baseline asked once per sample:

| | result |
|---|---|
| Verdict | **`INTERPRETABLE`** (the harness's own rule; the placeholder-baseline block is satisfied) |
| Jev better | citation support 0.667 → 0.833; unsupported-claim rate 0.667 → 0.500 |
| Jev worse | `criterion_error` 0.000 → 0.333 (one case of three); `key_fact_retention` 1.000 → 0.000 (one case of two) |
| Tie | `intent_accuracy` 0.667 on both sides, and every other metric with a population |
| Populations | 1–8 cases per metric; `retrieval.support.v1` has **0** on this split, so the task's first promotion candidate has no live number yet |
| Cost effect | a Jev-answered question removes its DeepSeek call: −9/−17/−27 across arms C/D/E |
| Promotion | **none.** Everything stays `shadow`; the mechanism now exists (`JEV_DEFINITION_MODES`, `JEV_BACKEND_ARCHITECTURE_FINAL.md` §3) and must not be used until this gate passes for that definition |

Two methodology traps this round produced, recorded because each changes what a number means: the arms
were each re-asking the baseline, so they were not a controlled difference until `memoise_predictor`
asked each sample once (before that, a definition **no arm arms** differed between arms); and an
`intent_accuracy` "regression" in one summary was produced by subtracting a number from one run from a
number from another — **two runs must never be subtracted**, and the per-case record now exists so
that class of mistake is visible rather than plausible. Full detail:
`JEV_CALIBRATION_AND_ABLATION_REPORT.md` §9.

---

## 1. Data

| Asset | Detail |
|---|---|
| Judgment dataset | `benchmarks/jev-judgments.dataset.json` — 310 samples over the catalog's definitions plus trajectory, image and locator families |
| Split manifest | `benchmarks/jev-calibration.split.json` — train 196 / calibration 47 / test 67, assigned by `(document_id, node_id, question_family)` so a question variant cannot leak across splits; content hash recorded and recomputed by the builder |
| Label tiers | `OBJECTIVE_VERIFIED` (a rule, id or sum decides it), `SOURCE_REVIEWED` (course source + review reason recorded), `SILVER_DEEPSEEK` (a model suggestion, explicitly not human gold), `DISPUTED` (both readings written down) |
| Threshold policy | fitted on the **calibration** split only; the test split is opened once for the final evaluation. No global `0.8`-style acceptance constant |

Component sets for the six enhancement modules extend the same dataset with module-specific families
(extraction fields, entity pairs, evidence pairs, citation claims, capability requests, tool
proposals). Each module ships its own switch so a component ablation can turn it off without touching
the main arms.

## 2. Arms

Main ablation (frozen; historical definitions unchanged):

| Arm | Contents |
|---|---|
| A | DeepSeek + deterministic only, **no Jev** |
| B | A + `retrieval.support.v1` rerank |
| C | B + context / intent / pedagogy |
| D | C + coverage / assessment criterion review |
| E | D + citation support / span selection |

Component ablations (each module on/off against the same A baseline): `ExtractionVerification`,
`EntityResolution`, `EvidenceConsistency`, `ClaimCitationAudit`, `CapabilityRouter`, `ToolIntentCheck`.

## 3. Metrics

Retrieval and evidence: Recall@K, MRR, NDCG, exact-locator accuracy, citation support accuracy and
unsupported-claim rate, context anchor retention, condition distinction, conflict false-positive rate.
Routing and capability: intent accuracy, capability misroute rate, `NO_SKILL` quality.
Extraction: field false-acceptance and false-rejection (a wrong value accepted is worse than a value
sent for review).
Tools: tool false-allow and false-block; unnecessary-approval count.
Learning and assessment: coverage false-confirm/false-miss, criterion error, score error, pending-review
rate. Cost and time: end-to-end success rate, p50/p95 latency, Jev calls/tokens/cost, DeepSeek
calls/cost, failure rate.

Hard invariants that any run must also satisfy, checked deterministically rather than scored: no
permission leak, no plan disclosure, no hidden-answer exposure, no duplicate grade write on replay, no
node-id or file mutation.

## 4. Honesty rules (enforced in code, not by convention)

1. Metrics read **labels only**; a model's own confidence or probability is never ground truth.
2. A `fake` transport run is tagged `NON_INTERPRETABLE_PLUMBING_ONLY`; `compare_jev_arms` returns
   `NOT_INTERPRETABLE` and raises if a quality claim is requested.
3. A live run is interpretable only on a labelled dataset — never on the shipped example.
4. A family whose non-Jev baseline is a placeholder (abstention or a service default) is named in
   `placeholder_baselines` and blocks an interpretable verdict until the real baseline is injected.
5. A passing test set means "these samples passed", not "the system can never misjudge".

## 5. Promotion gate

Per definition, never as a group. The intended first promotions are `retrieval.support.v1` plus at
least one of context/intent/pedagogy, each only after a documented non-inferiority result on the
calibration and test splits. Citation support, extraction verification and the tool-intent check may
influence behaviour only with an acceptable error rate; coverage and assessment remain advisory even
when enabled — the deterministic backend keeps the final word. A definition that does not clear the
gate stays `shadow`, and the final report must say so rather than lower the bar.

## 6. Reproducing a run

```
services\rag-api\.venv\Scripts\python.exe scripts\build_jev_dataset.py --validate --stats
services\rag-api\.venv\Scripts\python.exe scripts\run_jev_semantic_ablation.py --arm all --transport fake --out <fresh path>
services\rag-api\.venv\Scripts\python.exe scripts\calibrate_jev.py --help
```

The offline run proves wiring only. Producing a real result additionally needs
`TYPESAFE_API_KEY` (+ the pinned `typesafe-sdk`) and the DeepSeek key with an approved ceiling, as
listed in `MINIMAL_OWNER_ACTION_CARD.md`.

## 7. End-to-end journeys are a different kind of measurement, and now exist (round 90)

Everything above measures a *definition*: does it answer correctly, and does using it change a
metric. Neither question answers "does the product do anything with the answer". Round 90 added the
second kind for modules B, C, D and F — browser journeys over the shipped deployment whose assertions
are on what a learner's own client receives (citation cards, the knowledge tree, the task board):

| Journey | Configuration | What it measured |
|---|---|---|
| alias retrieval; two senses not merged; a task difference labelled and both kept; an unsupported figure flagged in code with the source still shown; the Jev-unavailable shape | none needed | **5 passed**, and the live promoted runs repeat them |
| genuine contradiction with both fragments kept | live key + `evidence.consistency.v1=on` | **passed**, 29.1 s |
| explicit authorised write not over-blocked | live key + `tool.intent.v1=on` + enforce | **passed** |
| write refused when the guard cannot answer | enforce + unreachable endpoint | **passed**, zero model calls |

Cost of that live run, from its own receipt store: **169 decisions, all `outcome=ok`, all carrying a
`model_version`**, latency 0.68–1.35 s. The number comes from `jev_decision_receipts`, not from an
estimate.

**What these journeys do not measure, stated so they are not read as more than they are:** they are
not the A–E or component ablation, they do not touch the test split (still deliberately unrun), and
they do not change any definition's mode in the committed configuration. Two module-level facts they
did establish by failing first: module D's layer 1 was pointed at the wrong database, so no citation
verdict had ever reached a reader; and the tool-intent guard's 1.5 s default sits barely above the
measured decision latency, so an `enforce` deployment needs a larger budget.

## 8. The component ablation: a metric with no samples is not a result (round 91)

The six component arms are the measurement half of §10 — one arm per structured module, each turning
on exactly its own decision key(s). They exist, and they run. What they could not do was produce a
**complete** table, because the labels are split across two datasets on purpose and the CLI read one:
`benchmarks/jev-judgments.dataset.json` labels the citation pair (42 + 16 samples) and none of the four
module-specific families, while `benchmarks/jev-module-judgments.dataset.json` labels
extraction/entity/consistency/capability/tool (7 each) and no citation sample. Run against either file
alone, five arms — or the sixth — print only `INSUFFICIENT_SAMPLES`, which is a statement about the
pairing, not about the system.

The pairing is now in the code rather than in a document: component arms read both datasets, each
metric keeps its own population, the artefact names the dataset behind every metric, and a component
run in which **no** metric has a sample is refused instead of written. The A–E arms are unchanged.
Offline, on this revision, all six arms measure in one command and the verdict is still
`NOT_INTERPRETABLE`, because the transport is still fake — the numbers say the arms compute over the
right samples and nothing about quality.

The live version of that run is **NOT_RUN**, and the reason is budget rather than capability: it costs
**93** Jev decisions (counted, not estimated — `M-CITATION` 58, the other five 7 each, no DeepSeek
call), against a ≤300 ceiling with 268 already spent. The exact command is in
`MINIMAL_OWNER_ACTION_CARD.md` §1b.

## 9. §16's ten verifications, item by item

§16 of the task names ten properties the acceptance must demonstrate. Naming the suite is not
evidence, so each row below names the journey and what it actually asserts. Two rows are deliberately
marked **partial** rather than claimed.

| §16 verification | Journey (file) | What the assertion actually checks | Status |
|---|---|---|---|
| 中文别名找到英文材料 | `jev-structured.spec.ts` | a Chinese question returns a citation card for a page that contains only the English term, and `user_text` is the question verbatim | PASS (credential-free) |
| 同词不同义不错误合并 | `jev-structured.spec.ts` | two senses come back as separate cards with different `document_id`, and the tree's node identity/title/parent/position is unchanged across the run — in the live promoted shape too | PASS |
| 精确题号不被语义替换 | `jev-structured.spec.ts` (module A journeys) + `test_real_course_golden.py::test_real_exact_locator_is_course_isolated` + `test_rerank_exact_target_keeps_slot_under_hostile_rerank` | the parsed label is verified and the locator actually used is reported; an exact target keeps its slot under a hostile rerank; and an exact locator is course-isolated | **PARTIAL**: the slot-preservation property is asserted offline against a hostile rerank and never end-to-end against a *live* rerank, because that needs `retrieval.support.v1` promoted, which the quality gate has not allowed |
| 错误引用不标supported | `jev-structured.spec.ts` | every card whose claim asserts an absent figure is `NOT_ADDRESSED_IN_AVAILABLE_EVIDENCE` at layer `quote` with zero model calls, the cards are still rendered with the unverified marker, and the control figure a page does state is not flagged | PASS |
| normal/Thinking 不被 skill 误选 | `jev-structured.spec.ts` + `codex-audit.spec.ts` | "answer only" does not take the teaching flow and spends no Jev call, a normal teaching request does, and both Normal and Thinking modes go through the integrated services | PASS |
| 未揭晓答案不暴露 | `codex-audit.spec.ts` | an un-revealed exercise's answer canary is absent from **four** payloads (`/runs/{id}`, `/runs/{id}/events`, `/pairs/{id}`, `/exercises/{id}`) and from the page body, then present after reveal and after a reload | PASS |
| 错误工具写操作被阻止 | `jev-structured.spec.ts` | with the guard enforcing and the endpoint unreachable, the proposed write is refused (`CONFIRMATION_REQUIRED`, `fallback:unavailable`, `jevCalls: 0`) and the task board is byte-identical | PASS |
| 合法明确工具操作不被过度阻断 | `jev-structured.spec.ts` | the same explicit message creates the task under `enforce` with a live credential and a raised budget | PASS (live) |
| private cache 不跨用户 | `learning.spec.ts` "two students stay isolated while an admin sees only the submitted Overlay snapshot" + `test_cache_scope_is_owner_scoped_and_never_crosses_users` | two identities cannot see each other's learning state, and a Jev cache key derived from the caller cannot serve user-b user-a's judgment | **PARTIAL at deployment level**: the browser deployment injects **one** identity (`AUTH_TEST_USER_ID` + `test-session-token`), so the cross-user Jev-cache property is pinned by unit tests, not by a browser journey. Stated rather than implied |
| Jev 断开系统安全降级 | `jev-structured.spec.ts` (two journeys) | with no credential every decision reports `used_jev: false`, cards get `INSUFFICIENT_CONTEXT` rather than a fabricated verdict, a complete answer still arrives; and the tool-intent guard refuses rather than allowing | PASS |

**The §16 operational chain**, link by link, with the journey that covers it (all in the browser gate):
file upload and indexing — `coursemate.spec.ts` ("creates, indexes, teaches from, and deletes a
private course") and `ui-refresh.spec.ts` ("lists real course files, uploads a private one, previews
it, and offers download"); retrieval and Jev relevance — the `jev-structured` alias and consistency
journeys above; conflict/condition judgement — `jev-structured` ("fragments from different tasks…",
"a genuine contradiction…"); DeepSeek teaching — `v3-learning.spec.ts` ("V3 private image problem
teaches and returns across browser contexts", i.e. the image path as well); citation verification —
`jev-structured` (module D); coverage — `ui-refresh.spec.ts` ("teaching a node from the shell books
reviewed coverage end-to-end"); the five-question assessment, grading and raw score —
`ui-refresh.spec.ts` ("a node assessment runs the real V3 flow: start, answer, submit, grade" and
"renders the real V3 result instead of raw JSON"); explanation — `ui-refresh.spec.ts` ("a problem's
steps stay in the problem pane and keep the detached detail flow") and `codex-audit.spec.ts`
("supplied problem exposes steps and opens explanation"); node result — `ui-refresh.spec.ts` ("the
knowledge tree renders the seeded hierarchy with real V3 statuses"); history — `ui-refresh.spec.ts`
("the original V3 question history stays readable and read-only").

One structural constraint behind the second PARTIAL row, stated once because it explains several
limits: the browser deployment shape authenticates with a single injected identity, so any property
that needs *two* real users (private cache isolation, cross-user retrieval) is pinned by unit or
in-process tests rather than by a journey. Adding a second injected identity is a product-code change
for test convenience and has not been made.



