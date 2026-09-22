# Evidence & Citation Audit (modules C and D)

Status: **implemented and tested offline** (FakeTransport only). No live Jev call is
made anywhere in this round; nothing here is a live quality result.

| Module | File | New definition | Registered in catalog? |
|---|---|---|---|
| C — `EvidenceConsistency` | `app/jev/evidence_consistency.py` | `evidence.consistency.v1` (Choice) | **No — pending** (module constant) |
| D — `ClaimCitationAudit` | `app/jev/citation_audit.py` | _none_ (reuses `source.supports_claim.v1` + `source.select_span.v1`) | n/a |

---

## Module C — EvidenceConsistency

### Position in the chain

```
permissions → exact locator → recall → merge/dedupe → relevance (RRF + rerank)
→ condition/conflict check (EvidenceConsistency) → evidence pack → DeepSeek
```

It runs **after** the global RRF fusion and the Jev rerank and **before** the
evidence pack is built. It is an annotation layer: it never reorders, drops or
adds a candidate, so the fixed retrieval rules cannot regress here.

### Relations (the `evidence.consistency.v1` Choice candidates)

| Relation | Meaning | Business handling |
|---|---|---|
| `SAME_CONTEXT_CONTRADICTION` | a genuine conflict under identical assumptions | keep **both** sources; ask DeepSeek to explain the conflict and its boundary |
| `DIFFERENT_ASSUMPTIONS` | each source valid under its own stated conditions/scope | explained as different scopes — never a conflict |
| `VERSION_OR_TASK_DIFFERENCE` | different revisions, or different sections/questions | deterministic; a newer document never overrides an older conclusion |
| `COMPATIBLE` | agree or complement | no action |
| `INSUFFICIENT_EVIDENCE` | fragments too thin to judge | one bounded extra read or an explicit insufficiency |

### Bounded comparison (no O(n²) model comparison)

1. Code first narrows candidate **pairs** deterministically:
   * same **document** with a different **version** → `version` (deterministic);
   * same **document** with a different **section/locator** → `task` (deterministic);
   * same **numeric value/quantity** (e.g. both mention `5%`) → `variable`;
   * same **significant concept token** → `concept`.
2. Only *adjacent* candidates within a group are paired, so the pair count is
   linear in the number of candidates — the model never sees a full cross product.
3. Version/task pairs are resolved deterministically (zero Jev calls).
4. The remaining (semantic) pairs are handed to Jev **at most `DEFAULT_MAX_PAIRS = 8`
   per request** (the owner's 12–16-candidate window).
5. The report records `checked_pairs`, `unchecked_pairs`, `comparable_pairs` and
   `total_possible_pairs` (n choose 2), so a caller can never be led to believe the
   whole corpus was compared pairwise.

### Output handling

* `ConsistencyReport.dropped_ids` is **always empty** — no source is ever dropped,
  and a lower Jev score is never a reason to drop (there are no scores here).
* `needs_deepseek_conflict_explanation` is True only when a
  `SAME_CONTEXT_CONTRADICTION` was found; `deepseek_conflict_prompt()` builds the
  explanation request while keeping both sources.
* `requested_extra_reads` lists at most 2 candidate ids for a single bounded extra
  read when a real Jev `INSUFFICIENT_EVIDENCE` is returned.
* A prompt-injection signal is **only a marker**: `prompt_injection_markers` lists
  the candidate ids; nothing is dropped, and no permission/safety decision is made.
* A newer document is never allowed to override older conclusions unless an
  explicit version/correction relation exists; version differences surface as
  `VERSION_OR_TASK_DIFFERENCE`, never as an override.

### The pending definition is not registered

`evidence.consistency.v1` is held as `EVIDENCE_CONSISTENCY_KEY` and built as a
module-level `DecisionDefinition` (`_EVIDENCE_CONSISTENCY_DEFINITION`) so the
gateway can evaluate it **today** (modes/bounds/receipts apply exactly). It is
**not** in `decision_catalog.json`; the exact proposed entry and the registration
request are in `STRUCTURED_DECISION_CONTRACTS.md`.

---

## Module D — ClaimCitationAudit

One service merging the two citation cases (case 4 + case 10). There is **no
second citation service** and no new citation definition — it reuses
`source.supports_claim.v1` (Noul) and `source.select_span.v1` (Choice).

### Three layers (only layer 3 is semantic)

| Layer | Question | Who decides | Jev calls |
|---|---|---|---|
| 1 — existence + authorization | does the cited document/version/location exist and is the caller authorized? | deterministic backend (`EvidenceResolver.resolve`) | **0** |
| 2 — quote existence | does the quoted text/number actually appear in that document? | deterministic (`quote_exists`) | **0** |
| 3 — claim support | does the located evidence support the specific claim? | Jev (`source.supports_claim.v1` / `source.select_span.v1`) | 1–2 |

### Verdict labels

| Label | When |
|---|---|
| `SUPPORTED` | a real Jev support probability ≥ 0.75 |
| `PARTIALLY_SUPPORTED` | probability in [0.5, 0.75) |
| `CONTRADICTED` | a direct, deterministic, unit-aware numeric conflict |
| `NOT_ADDRESSED_IN_AVAILABLE_EVIDENCE` | quote absent, or a strong "no" with no direct conflict |
| `INSUFFICIENT_CONTEXT` | fallback / no Jev signal |
| `REJECTED` | layer-1 failure (`unauthorized` / `missing`) |

### Rules enforced

* **"not mentioned in the fragment" ≠ "the document disproves it".** A strong
  "no" without a direct numeric conflict is `NOT_ADDRESSED_IN_AVAILABLE_EVIDENCE`,
  never `CONTRADICTED`.
* **"the quote exists" ≠ "the claim is correct".** Layer 2 only gates passage to
  layer 3; `SUPPORTED` requires a real Jev signal (`is_verified`). `test_quote_exists_is_not_reported_as_claim_correct` pins this.
* **Jev never invents a page, quotation or URL.** Span/document ids come from the
  backend `EvidenceResolver`; `source.select_span.v1` may only select a
  backend-supplied span id (the gateway validates Choice against the supplied ids).
* **Whitespace normalization is traceable and lossless for meaning.** `normalize_whitespace`
  collapses whitespace runs only; a sign, inequality, number and unit all survive.
  `5%` and `5 percentage points` canonicalize to different units and can never match
  (`test_five_percent_is_not_matched_to_five_percentage_points`).
* **Streaming teaching.** Nothing is shown as verified before it is checked
  (`CitationAuditResult.is_verified`); the audit binds to the fixed message
  revision (`document_id` + `version`); a problem appends a correction or a new
  version rather than silently rewriting history (caller contract, documented in
  the module docstring). High-impact material (reference solutions, grading
  rationale) is held open until `is_definitive(result)` is True.
* **No external web fetching.** Verification is against the current course material
  only; a link inside a document is never turned into an arbitrary URL reader.

---

### A deterministic defect found and fixed while wiring this (round 25)

The unit-aware number check had a real bug that its own docstring claimed not to
have: the alternation `(%|percent|percentage\s+points?|…)` matches its **first**
alternative, so `percent` shadowed `percentage points` and "7 percentage points"
parsed as "7 percent". Against evidence text of "5%" that produced a *fabricated*
numeric contradiction — the one verdict class that can turn a strong "no" into
`CONTRADICTED`. The existing test only exercised the literal-quote path
(`quote="5 percentage points"`), so nothing caught it. Fixed by ordering the
alternatives longest-first, with:

* `test_percentage_points_are_never_read_as_percent` — different units with different
  values is `NOT_ADDRESSED_IN_AVAILABLE_EVIDENCE`, never `CONTRADICTED`;
* `missing_claim_numbers(claim, evidence_text)` — the deterministic half of layer 2
  for the teaching path, where a citation card carries no verbatim quotation: a
  figure the claim asserts but the cited source never states is `NOT_ADDRESSED…`,
  decided in code with **zero** model calls. Unit-aware, so `5%` is never satisfied
  by `5 percentage points`, and a unitless integer is never treated as an assertion;
* `test_missing_claim_number_is_detected_deterministically` covers both directions,
  the unitless case and a Chinese unit (`5℃`).

## Wiring status (honest, as of this round)

* **Module C — `MODULE_ONLY`.** `app/jev/evidence_consistency.py` is complete and
  tested, and `evidence.consistency.v1` is registered in the catalog (19
  definitions), but **no retrieval/evidence-pack call site invokes it yet**. No
  business effect is claimed for it. The intended insertion point remains the
  evidence-pack step in `V3DomainAdapter._retrieve`, between the fused candidate
  set (where entity relations are already resolved) and the DeepSeek prompt, with
  the rule that a genuine conflict keeps both sources and is explained by DeepSeek
  rather than resolved by deletion.
* **Module D — landed (round 25).** Both the pre-generation evidence bundle
  (`domain.py::_annotate_evidence` → `answers.evidence_bundle_support`) and the
  post-generation audit on the fixed message revision now run:

  1. **Production `EvidenceResolver`** — `app/jev/citation_evidence.py::DocumentEvidenceResolver`,
     constructed per request with the server-derived subject. It reuses the canonical
     rules rather than copying them: `can_read_document_version` (a non-raising wrapper
     over `_authorize_document_version`) for the document ACL and
     `ChunkRepository.resolve_document_chunks` (same `_source_access` scope as every
     other chunk query) for the text. It answers `ok` / `missing` / `unauthorized`,
     never raises on those outcomes, never returns another course's or another user's
     text, is version- and locator-aware, bounds the text, and writes nothing.
  2. **Claim→citation binding** — `cm_update.app.audit_answer_citations` extracts the
     sentence(s) that actually cite each `[Sn]` from the generated answer, audits them
     against the source the learner was shown, and records the verdict, the producing
     layer and the audited claim on the citation card the client already receives.
     At most 6 cards per answer bound the per-answer model budget.
  3. **Consumer** — the shipped shell marks only a *real* negative verdict
     (`apps/web/src/ui/citationSupport.js`): a contradicted or un-addressed citation
     gets a warning chip with an explanatory title, while a verified, partial, merely
     unchecked or legacy card renders exactly as before. High-impact gating
     (`is_definitive`) remains available to the assessment path; binding the reference
     solution to it is the next step, not something this round claims.
  4. **Shadow invariance** — with no semantic layer configured the cards are returned
     **byte-identical** to before the audit existed (`test_no_semantic_layer_returns_the_cards_unchanged`),
     layer 2 still decides for free, and a shadow decision annotates without altering
     or dropping a card. An audit failure records itself on the cards rather than
     losing an answer that was already generated.
* Nothing here is `on`/`advisory`: with no TypeSafe credential every evaluation stays
  in `shadow`, so `used_jev == False` and the deterministic annotation is what the
  business uses.

## Tests

```
pytest tests/test_jev_evidence_consistency.py tests/test_jev_citation_audit.py -q
```

21 tests, covering: exact-target protection preserved; private candidates still
rankable; a genuine contradiction keeping both sources; a condition/version
difference not reported as a contradiction; the pair budget honoured with
unchecked pairs recorded; the three citation layers with layers 1–2 proven
deterministic (zero Jev calls when the quote is absent or unauthorized); `5%` vs
`5 percentage points` not treated as a match; "not mentioned in the fragment" not
reported as a contradiction; an unauthorized citation rejected; a prompt-injection
marker not deleting a document; fallback behaviour when the transport fails; and
no learning/grade writes.
