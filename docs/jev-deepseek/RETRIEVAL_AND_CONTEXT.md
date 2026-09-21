# RETRIEVAL_AND_CONTEXT

Scope: the integrated retrieval chain after this round — candidate recall per authorized scope,
ONE global ranking, exact-locator protection, context budgeting, and the (shadow-first) Jev
re-ranking hook.

## 1. The bug that was reproduced

`V3DomainAdapter._retrieve` (pack finding `candidate_truncation`, `SOURCE_EVIDENCE.md` S03)
did:

```
official_hits = retriever.retrieve(scope="official")
hit_rows = [*official_hits, *retriever.retrieve(scope="mine")]   # append order
for index, hit in enumerate(hit_rows[: top_k * 2]):
    ...
    if len(sources) >= top_k: break                              # truncate by list position
    text = hit.content[: max_context_chars // max(index, 1)][:4000]
```

With `top_k = 2` and two candidates per scope the private candidates were retrieved and then
silently dropped: append order, not relevance, decided the output. The pack's probe returned
`['official-doc-1', 'official-doc-2']`; the same behaviour is now a permanent regression test.

## 2. The chain now

```
authorize course + workspace (unchanged ACL rules)
→ raw question + bounded history → query rewrite (reused legacy tutor/rewrite)
→ explicit file / page / question locator parsed (reused tutor/references)
→ per-scope recall: official scope + caller's private workspace scope
    (structured exact recall first when a locator is present, then hybrid keyword+vector)
→ dedupe by chunk id, keep per-scope rank evidence
→ ONE global ranking: reciprocal rank fusion over the authorized scopes
→ exact-target protection (referenced file/page/question keeps its slot)
→ boundary-aware text budgeting
→ public projection: S1..Sn assigned only here
```

Implemented in `services/rag-api/app/learning/retrieval_orchestrator.py`:

* `fuse_scoped_candidates(groups, top_k=…, rank_constant=60, scope_weights=None,
  exact_targets=…, max_candidates=40)` — each candidate contributes
  `weight / (rank_constant + rank)` per scope it appears in. Ranks are comparable across
  scopes **because every scope is already access-controlled**; scope identity is not a ranking
  score, so a private note in the same course competes on equal terms with an official
  fragment.
* The recall cap is applied **per scope** (`group.hits[:max_candidates]`). This is deliberate:
  the first version applied the cap while iterating scopes in append order, which reproduced
  the very bug being fixed — the first scope consumed the whole budget. The regression test
  (`…merges_private_candidates_before_top_k`) caught it with a 40-hit stub scope.
* `exact_targets_from_query(query)` extracts file names, `page N`/`第 N 页`, and
  `question N`/`第 N 题` references; matching candidates are ordered first and cannot be
  displaced by a semantically "similar" hit. (Requirement: an explicitly referenced question is
  a locked target, not a suggestion.)
* `budget_text(text, budget)` trims at the nearest paragraph/sentence boundary inside the
  budget instead of dividing the context budget by list position, so formulas, units or table
  headers are not cut in half; truncation is marked with `…`.
* `trace_digest(fused)` produces an audit digest of the ranking decision (ids, scores, scopes,
  exact flags) without storing raw text.

`V3DomainAdapter._retrieve` now:

1. reuses `rewrite_retrieval_query` (a `RewriteResult`, not a string) when history is present;
2. reuses `parse_query_reference` + `retriever.retrieve_structured` for explicit locators;
3. recalls both authorized scopes with the configured recall width
   (`Settings.retrieval_candidates`, default 40 — the plan's starting point, configurable and
   explicitly NOT claimed to be a measured optimum);
4. fuses once and projects at most `top_k` items (default 6) with sequential `S1..Sn` ids;
5. never lets a scope's identity short-circuit the ranking, and never assigns citation ids
   inside the model.

## 3. Context pack and continuity (implementation + plan alignment)

* Text budget: total `Settings.max_context_chars` (default 18 000) divided across the fused
  winners with the boundary-aware trimmer above.
* Continuous chapter teaching: the plan requires a real chapter evidence pack (continuous
  content, worked examples, key figures, related exercises) instead of pretending a handful of
  top chunks is a full read; that remains an explicit follow-up item tracked in
  `RETRIEVAL_AND_CONTEXT` + `PRODUCTION_ACCEPTANCE` rather than being claimed as done here.
* Permanent history is never deleted: the shared anchor (course/node/chapter, uncovered
  REQUIRED items, original values/symbols, return point, `Next_Action`) plus bounded recent
  messages stay in the prompt. Only *optional* old segments may be dropped by the context
  selector, and in shadow mode the deterministic selection is what is used.

## 4. Jev re-ranking hook (shadow by default)

The semantic layer sits **after** fusion and can only reorder candidates that are already
authorized and already in the fused set. Contract enforced by tests:

* Jev never adds, invents or drops an exact-target hit.
* A Jev timeout/unavailable/invalid response leaves the deterministic ranking in place and
  records a receipt; no state is written.
* Cross-user isolation: a cached judgement is never reused for another owner scope, and a
  material-revision change invalidates the cached judgement.

## 5. Verification in this round

| Check | Test | Result |
|---|---|---|
| private candidates enter through global ranking | `test_probe_retrieval_merges_private_candidates_before_top_k` | pass (was failing) |
| exact locator keeps its slot | `test_probe_exact_target_is_not_replaced_by_rank` | pass |
| citation ids assigned only at projection | same tests assert `S1`, `S2` | pass |
| existing dual-mode/tree behaviour | `pytest tests/test_ui_extension_tree_and_dual_mode.py -q` | pass |
| per-scope cap cannot starve later scopes | merge regression uses a 40-hit stub scope | pass |

## 6. Not run / open

* A/B/C/D ablation of Jev re-ranking on labelled data: NOT_RUN (no TypeSafe credentials; the
  plan's 200 labelled judgements are a plan, not a result).
* Continuous chapter evidence packs and parent/adjacent expansion beyond the current
  budget: implemented only to the depth covered by the orchestrator above; deeper expansion is
  tracked as remaining work rather than claimed.
