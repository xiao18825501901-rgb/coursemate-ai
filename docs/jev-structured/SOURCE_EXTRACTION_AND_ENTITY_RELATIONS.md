# Source Extraction & Entity Relations

This document has two halves. The first — **Module A: ExtractionVerification** — is
owned by the extraction workstream and is complete below. The second —
**Entity Relations** — is owned by nobody yet and is left as a clearly marked
stub at the end.

---

## Module A — ExtractionVerification

**Files owned by this workstream:**

* `services/rag-api/app/jev/extraction.py`
* `services/rag-api/tests/test_jev_extraction.py`
* `docs/jev-structured/SOURCE_EXTRACTION_AND_ENTITY_RELATIONS.md` (this file)

**Goal.** A vision/parser pass turns questions, tables, figures and (student-typed
or uploaded) answer fields into structured fields. This module stops
*silently-wrong extraction* from poisoning teaching and grading. The rule is
fixed: **deterministic checks run first; Jev judges only the semantic residue;
only the flagged field / source region may be repaired, within budget.**

### 1. The normalized extraction record

`ExtractionRecord` (a dataclass, with `as_dict()`) carries at least:

| field | type | meaning |
|---|---|---|
| `source_id` | `str` | source document id |
| `source_version` | `str` | source document version |
| `page` / `region` / `span` | `int\|None` / `str\|None` / `(int,int)\|None` | the locator of the field |
| `question_id` | `str` | question id |
| `part_id` | `str\|None` | sub-question / part id |
| `field_name` | `str` | the structured field (e.g. `mass`, `answer`) |
| `candidate_value` | `Any` | the value the parser believes it read |
| `unit` | `str\|None` | the value's unit |
| `uncertainty` | `float\|None` | the extractor's own confidence, 0..1 |
| `extraction_version` | `str` | the parser/extraction pass version |

Extra fields carry the *bounded residue* the semantic judge may see and the repair
rules need: `supplied_text` (the source text of exactly the region that was read —
never the whole document), `role` (see §5), `table_rows` (a parsed table for the
structural check), and `unreadable` (a hard signal that the region/character could
not be read).

`record.identity()` is a stable hash of the *slot* (source/version/locator/
question/part/field/extraction-version), deliberately excluding the candidate
value, so an original record and its repaired form share an identity and the
single-repair bound applies across them.

### 2. Deterministic checks (all in code — zero Jev calls)

`run_deterministic_checks(...)` runs, in order, and collects **every** failure
(no short-circuit):

1. **required fields present** — `source_id`, `source_version`, `question_id`,
   `field_name`, `candidate_value` (not `None`), `extraction_version`, and at
   least one of `page`/`region`/`span`.
2. **numeric parse** — when the backend's `FieldSpec` says `kind == "number"`, the
   candidate must parse as a plain number.
3. **unit consistency** — when the backend's `FieldSpec` declares an
   `expected_unit`, the record's `unit` must be present and match it
   (case/space-insensitive).
4. **question-number shape** — `question_id` (and `part_id`, when present) must
   match the configured pattern (default `^[Qq]?\d+$` / `^[A-Za-z]?$`).
5. **table structure** — when `table_rows` is present: every row has the same
   column count, and no *shifted cell* (an empty cell under a populated header
   column) exists.
6. **source id exists** — via the injected `SourceRegistry`.
7. **source in scope** — the source must belong to the authorized `course_scope`.

A record failing any of these is `REJECTED` with **zero** Jev calls
(`path = "deterministic_reject"`, `jev_calls == 0`).

### 3. The semantic judgment (Jev, over the residue only)

Only after every deterministic check passes does the verifier reach Jev, and only
with the *residue*: `question_id`, `part_id`, `field_name`, `candidate_value`,
`unit`, `supplied_text`, and the `source_region` locator. It never sees the whole
document, adjacent rows, or outside knowledge.

The question asked is the intended new definition `extraction.field_grounded.v1`
(a `Choice`): does the value actually belong to this question/condition; was it
copied from an adjacent example; was a negation or constraint dropped; does a
student answer map to the right sub-question; is the supplied source enough.

Candidates: `GROUNDED`, `WRONG_FIELD`, `NEGATION_LOST`, `CONSTRAINT_LOST`,
`SOURCE_INSUFFICIENT`, `UNCERTAIN`.

* `GROUNDED` → `ACCEPTED` (`path = "jev"`).
* `WRONG_FIELD` / `NEGATION_LOST` / `CONSTRAINT_LOST` / `SOURCE_INSUFFICIENT` →
  `FLAGGED` and a bounded repair is planned (if allowed — see §4).
* `UNCERTAIN` → `NEEDS_REVIEW`.

The definition is implemented against `JevGateway` via a locally built
`DecisionDefinition` (module constants `EXTRACTION_FIELD_GROUNDED_KEY` /
`EXTRACTION_FIELD_GROUNDED_VERSION`). It is **not** registered in
`decision_catalog.json` — see the registration request in §7.

### 4. A Jev agreement is NOT vision verification

This is stated in the module docstring and pinned by
`test_unreadable_region_returns_needs_review_without_jev`. If a character is still
unreadable, or the value came from an unreadable region (`record.unreadable`), the
result is `NEEDS_REVIEW` with the source region preserved — **never** a confident
acceptance, even if a Jev responder says `GROUNDED`. Jev can only confirm that the
*already-read* text supports the field; it cannot read pixels.

### 5. Bounded repair

At most **one** repair step per extraction (`MAX_REPAIR_STEPS_PER_RECORD = 1`),
planned as an explicit stage with its own budget and receipt; no SDK implicit
retry; never a whole-document re-read. A `RepairRequest` pins the exact field,
question and source region, with `kind = "re_extract"` for source/reference
material and `kind = "legibility"` for a student's own content.

If the current budget or user mode does not allow the extra model call, the
verifier returns `NEEDS_REVIEW` (or a minimal confirmation request) and never
upgrades the model tier or calls another generation provider — the only model the
verifier ever reaches is the Jev gateway.
(`test_budget_refused_repair_degrades_instead_of_upgrading`.)

### 6. Never help a student cheat

`role ∈ {student_answer, draft, transcription, submission, grading_revision}` is
cheating-sensitive:

* repair `kind` must be `legibility` (clarify characters), never a rewrite;
* a repair that would change a student answer *into* the known correct answer is
  refused (`STUDENT_ANSWER_REWRITE_REFUSED`);
* drafts / transcriptions / submissions / grading revisions stay separate, and a
  reference solution is verified without reading any student answer — the residue
  state is built only from the record's own slot.

(`test_student_answer_rewritten_to_correct_is_refused`,
`test_student_legibility_repair_not_to_correct_is_allowed`.)

### 7. Catalog-registration request (for the catalog workstream)

`decision_catalog.json` is owned by another workstream and was **not** edited.
Please register the following as definition #13, consistently with its own tests:

```json
{
  "key": "extraction.field_grounded.v1",
  "primitive": "Choice",
  "required_state": [
    "question_id", "part_id", "field_name",
    "candidate_value", "unit", "supplied_text", "source_region"
  ],
  "criteria": {
    "GROUNDED": "The candidate value actually belongs to this question/condition and is fully supported by the supplied source text",
    "WRONG_FIELD": "The value was copied from an adjacent example or a different field, not this question/condition",
    "NEGATION_LOST": "A negation (not/no/except/unless) was dropped, inverting the value",
    "CONSTRAINT_LOST": "A constraint or condition (range, unit, scope, if/when) was dropped from the value",
    "SOURCE_INSUFFICIENT": "The supplied source text is not enough to confirm the value belongs here",
    "UNCERTAIN": "Cannot resolve reliably from the supplied text"
  },
  "instructions": "Judge ONLY the supplied source text: does the candidate value actually belong to this question/condition, or was it copied from an adjacent example, or a negation/constraint dropped? Use no outside knowledge; never confirm a value the supplied text does not show; when the text is insufficient say SOURCE_INSUFFICIENT.",
  "failure_policy": "NEEDS_REVIEW; never a confident acceptance",
  "cache_scope": [
    "authorization_scope", "course", "workspace", "material_revision",
    "node_spec_version", "question_definition_hash", "input_hash",
    "provider_model_version"
  ]
}
```

* **id / version:** `extraction.field_grounded.v1` / `1.0.0-design` (the current
  catalog version).
* **primitive:** `Choice`.
* **fallback (failure policy):** `NEEDS_REVIEW` — deterministic result, never a
  confident acceptance.
* **runtime mode:** stays `shadow` (the catalog default) like the other 12 until a
  credential exists; the verifier respects `off`/`shadow`/`on` via the gateway.

The module already builds this exact `DecisionDefinition` from module constants
(`field_grounded_definition()`), so registering it in the catalog will not change
behaviour — it only makes the definition visible to `Catalog`-aware tooling.

### 8. Degradation

Jev unavailable / invalid / oversized / off / shadow degrades to the deterministic
result plus `NEEDS_REVIEW` where the decision mattered, with a typed
`FallbackReason` (`jev_unavailable`, `jev_invalid_response`, `input_too_long`,
`jev_off`, `jev_shadow`, `no_service`, …). No learning/grade/coverage state is
written; the only table involved is `jev_decision_receipts`
(`test_verification_writes_only_receipts`).

### 9. Test coverage

`tests/test_jev_extraction.py` (16 tests, offline `FakeTransport` only) covers:
deterministic rejections (missing unit / shifted table cell / out-of-scope source)
with zero Jev calls; a grounded acceptance; wrong-field and negation-lost; the
unreadable-region `NEEDS_REVIEW`; the single-repair bound; a budget-refused repair
that degrades instead of upgrading; a student answer that would become correct
being refused; a fallback on an unavailable transport; and no learning/grade row
writes.

---

## Module B — CourseEntityResolution

**Files owned by this workstream:**

* `services/rag-api/app/jev/entity_resolution.py`
* `services/rag-api/tests/test_jev_entity_resolution.py`
* `docs/jev-structured/SOURCE_EXTRACTION_AND_ENTITY_RELATIONS.md` (this half)

**Goal.** Relate the semantic objects inside a course — bilingual terms, aliases,
the same concept, question variants, material versions, duplicate evidence —
**without merging anything**. The rule is fixed: **deterministic checks run first;
Jev judges only the residue; relations are proposals only, never mutations.**

### 1. The entity object

`EntityObject` (a frozen dataclass) is the normalized object handed to the
resolver. It carries: `object_id` (the stable backend id — knowledge-node id, term
id, question id, material id, evidence id), `kind` (`term | concept | question |
material | evidence`), `course_id`, `material_revision`, `label`, `content` (the
bounded text to hash and compare), `source_version`, and `aliases` (the
already-*accepted* aliases the backend owns). `content_hash()` is the sha256 of the
exact content bytes.

### 2. Deterministic candidate generation (all in code — zero Jev calls)

`generate_candidate_pairs(objects, …)` narrows an already-authorized in-scope set
into pairs, each classified in priority order:

1. **exact id** — same `object_id`, same revision → `SAME_CONCEPT` (deterministic).
2. **version** — same `object_id`, different `material_revision` →
   `DOCUMENT_VERSION_RELATION` (deterministic).
3. **content hash** — different ids, byte-identical non-empty content →
   `SAME_CONCEPT` (duplicate evidence, decided by hash).
4. **accepted alias** — one object's label/id is in the other's `aliases` →
   `ALIAS` (authoritative, deterministic).
5. **title normalization** — same normalized label → semantic residue (offered to
   Jev).
6. **bounded local similarity** — token-set Jaccard ≥ threshold → semantic residue
   (offered to Jev).

Deterministic reasons (1–4) carry a `deterministic_relation` and cost **zero** Jev
calls; the model only ever sees the title/similarity residue, one pair per call.

Candidate generation is **symmetric and order-independent**: every unordered pair
is scored the same whichever object is `left`, ids are canonicalized
(`left_id <= right_id`), and the set is sorted by a stable key (deterministic
pairs first, then strongest score, then canonical ids). An optional
`max_candidate_pairs` cap is applied **after** scoring in that canonical order, and
the number of pairs it drops is recorded in `dropped_by_cap` (the report exposes
`scored_pairs = candidate_pairs + dropped_by_cap`), so a cap can never be mistaken
for "there was nothing else to compare".

### 3. The semantic judgment (Jev, over the residue only)

`resolve_relations(gateway, objects, course_id=…, material_revision=…, max_pairs=…,
max_candidate_pairs=…)` runs the deterministic pairs in code and hands the semantic
pairs to the catalog's own `entity.relation.v1` (a `Choice`), with state exactly
`{left, right, course_id, material_revision}` where `left`/`right` are the bounded
`{kind, label, content, source_version}` views. Candidates are the seven
`SAME_CONCEPT / ALIAS / QUESTION_VARIANT / DOCUMENT_VERSION_RELATION /
RELATED_NOT_SAME / DIFFERENT / UNCERTAIN`. One relation per pair; at most
`max_pairs` (default 8) semantic pairs per request; the remainder is recorded in
`unchecked_pairs` (distinct from `dropped_by_cap`, which is the pre-Jev candidate
cap).

The definition is **already registered** in `decision_catalog.json`
(`entity.relation.v1`); this module calls `load_catalog().get(...)` and never
invents another id.

### 4. Similarity is not proof, and relations are never transitive

A local-similarity or normalized-title match only *offers* a pair; Jev may answer
`DIFFERENT` (a same-word pair such as "bank"/"bank" stays `DIFFERENT`, never
merged). A relation is never transitive by assumption: A≈B and B≈C never silently
relate A and C. Pair generation is pairwise only and produces no cluster id —
`RelationReport.merged_any` is always `False`.

### 5. Scope isolation and cross-user privacy

Candidate generation never queries the database: it pairs only the objects the
caller already authorized for the course/workspace. As a backstop,
`resolve_relations` drops any object whose `course_id` differs and names it in
`excluded_out_of_scope`, so an out-of-scope pair is never offered and another
user's private material is never compared.

### 6. Conservative query expansion

`expand_query(query, aliases=…, explicit_targets=…, max_aliases=…)` adds at most
`max_aliases` (default 3) *accepted* aliases; the original query is always the
prefix, and an explicit file/page/question target always outranks alias expansion
(expansion is skipped, so the target is never displaced). Aliases already present
in the query are skipped. Deduplication may fold duplicate evidence inside an
evidence pack, but the file list and shared snapshots keep every valid file, and
cross-user deduplication never reveals that another user uploaded the same
material.

### 7. Degradation

Jev unavailable / invalid / off / shadow / over budget returns `UNCERTAIN` (no
relation, `used_jev=False`); the original query is unchanged and retrieval is
unaffected. With no Jev service at all (`V3DomainAdapter(jev=None)`) the retrieval
path is byte-identical: no expansion input, no resolution, no proposal write. If
the `entity_relations` store is absent (an un-migrated database) the proposal
bookkeeping degrades to "nothing recorded" and retrieval still returns the same
deterministic order — proven by
`test_relation_bookkeeping_never_breaks_retrieval_without_the_store`.

### 8. Test coverage

`tests/test_jev_entity_resolution.py` (18 tests, offline `FakeTransport` only)
covers: byte-identical duplicates with zero Jev calls; a Chinese↔English accepted
alias; a same-word-different-meaning pair staying `DIFFERENT`; a question-variant
pair; a deterministic version relation; a non-transitive A/B/C chain that does not
merge; symmetric, order-independent candidate generation (same pair whichever
object is `left`); the post-scoring candidate cap with dropped pairs recorded; the
pair budget with unchecked pairs recorded; scope isolation (an out-of-scope pair
never offered); alias query expansion preserving the original query and never
overriding an explicit target; transport-failure degradation; and no writes
outside the receipt table.

The wiring itself is covered by `tests/test_jev_shadow_invariance.py`:
`test_alias_expansion_preserves_original_query_and_explicit_target`,
`test_fused_order_unchanged_under_shadow_and_unavailable` (byte-identical
`document_id` order across shadow, unavailable and `jev=None`),
`test_duplicate_evidence_is_recorded_as_a_proposed_relation` (one
`SAME_CONCEPT`/`content_hash` row, `status=PROPOSED`, `used_jev=0`, canonical ids,
source versions, course, idempotent on a second retrieval, and the duplicate is
*not* merged away on the path), and
`test_relation_bookkeeping_never_breaks_retrieval_without_the_store`.

### 9. Wiring — **LANDED** (entity resolution, extraction verification)

Host wiring: one shared `SemanticDecisionService` is built in
`app/main.py::create_app` and threaded to the adapter, and
`V3DomainAdapter.__init__` builds `CourseEntityResolver(jev.gateway if jev else None)`
— there is no second gateway.

1. **Query expansion — landed.** `_retrieve` calls
   `self.entity_resolver.expand_query(query, aliases=self._accepted_aliases(course_id, subject),
   explicit_targets=[target.raw for target in exact_targets])` after the
   history-rewrite block and before the first recall. Expansion is deterministic
   and never reaches Jev; the user's original query stays the prefix, only
   already-accepted aliases (from the authorized knowledge registry, private rows
   scoped to the subject) are added, and an explicit file/page/question target
   skips expansion entirely.
2. **Relation resolution — landed, proposal-only.** After `fuse_scoped_candidates`,
   `_resolve_entity_relations` builds `EntityObject`s from the already-authorized
   fused candidates and calls `resolver.resolve(..., cache_scope=<owner-scoped>)`.
   The returned relations are **persisted as proposals** into `entity_relations`
   (migration 029) with `status=PROPOSED`, `evidence`, `used_jev` and
   `receipt_id`, `UNIQUE(left_id,right_id,relation)` so a repeated retrieval is
   idempotent. Nothing is merged, renamed, reordered or deleted: the duplicate
   evidence stays in the returned sources, and only the backend may later move a
   row to `ACCEPTED`/`REJECTED`.
3. **Not part of this endpoint.** Folding duplicate evidence *inside* the evidence
   pack (while the file list keeps every valid file) remains a deliberate
   non-goal here: this path must not change what the learner sees while the
   definition is in shadow.
4. **Module A (ExtractionVerification) — wired in round 30.** The round-26 decision to leave it
   `MODULE_ONLY` was **wrong**, and the reason it was wrong is worth recording precisely: the
   investigation looked for a surface that produces a *document-side* field record, and missed the
   **query-side** parser `app/tutor/references.py::parse_query_reference`, whose output is not an
   annotation at all but a hard exact-locator filter.

   What the label does (this is the consumer the document-side surface lacked):

   * `ChunkRepository.structured_search` adds
     `json_extract(c.metadata_json,'$.question_number') = ?` **and**
     `json_extract(c.metadata_json,'$.question_part') = ?` to the `WHERE` clause, in the official
     scope *and* in the learner's private scope, and its hits are then placed at the **head** of the
     candidate list (`hits=[*official_structured, *official_hits]`);
   * `QaService.stream` derives `is_referenced_example` — and therefore `example_mode` — from
     `question_number is not None`.

   So an invented or mis-read label either suppresses legitimate exact recall or pins it onto the
   wrong sub-question, and it does so with a `locator` score of 1.0. A reproduced defect, measured
   before any change (six prose probes, five invented labels):

   | Query | Label before | Label after |
   |---|---|---|
   | `What does question 5 have to do with chapter 2?` | `number=5`, **`part="h"`** (from "have") | `number=5`, `part=None` |
   | `what does q mean in this context` | **`number="M"`**, **`part="e"`** (from "mean") | no label at all |
   | `question 3 marks distribution` | `number=3`, **`part="m"`** (from "marks") | `number=3`, `part=None` |
   | `How many marks is question 4 worth` | `number=4`, **`part="w"`** (from "worth") | `number=4`, `part=None` |

   The old pattern made the sub-part optional *and* unterminated
   (`(?:\s*[\(\uFF08]?\s*(?P<part>[a-z]|\d+)\s*[\)\uFF09]?)?`), so any word directly after the number
   donated its first letter as a sub-part, and the roman-numeral alternative matched the first letter
   of any following word. The parser now reads a sub-part **only when it is delimited** — parenthesised
   (`Question 1(b)`, `Q3(2)`) or a standalone token not glued to a following word (`q 2 b`) — and a
   roman numeral must not be followed by a word character. Every existing pinned case still parses
   (`test_reference_parser.py`, `test_real_course_golden.py`).

   The wiring itself (round 30):

   * `app/jev/reference_verification.py` — the adapter and the consumer. `reference_records` projects a
     present label into an `ExtractionRecord` (source = the learner's own normalised message, locator =
     the character span the label was read from), `verify_query_reference` runs the module-A pipeline
     over it and returns both the report and the reference the caller may actually use.
   * The semantic judgment goes through the **13th call site**
     `callsites.verify_extraction_field` → `SemanticDecisionService.field_grounded` (a bounded Choice
     whose candidate vocabulary is read from the catalog entry), so an extraction decision is
     observable and budgeted like every other business decision and never reaches the transport
     directly. `ExtractionVerifier` gained an optional `service` and now routes through it;
     `field_grounded_definition()` is projected **from the catalog** (which had already registered
     `extraction.field_grounded.v1`) with the module constants asserted against it.
   * Disposal — the only repair on this surface, and the answer to the round-26 objection about
     displacing the exact locator: a label is dropped **only** for a deterministic failure (the label
     is not well formed) or an affirmative Jev defect (`WRONG_FIELD` / `NEGATION_LOST` /
     `CONSTRAINT_LOST` / `SOURCE_INSUFFICIENT`). `UNCERTAIN`, `off`, `shadow`, no-service and timeout
     all keep the deterministic reference **exactly as it was** and only report `NEEDS_REVIEW`. A
     `GROUNDED` label from an enabled decision is used unchanged. The rule is verdict-driven rather
     than status-driven on purpose: reading only the status would let an exhausted repair allowance
     leave a label the model called wrong in place as a filter
     (`test_a_defect_drops_the_locator_even_when_no_repair_remains`).
   * Dropping a label can only ever **remove** a filter, so this module can never widen what a learner
     may read, add a source, or make an unauthorized chunk reachable; and a sub-part whose parent
     question is untrusted is dropped with it, because filtering on "part b" across every question is
     not the reference the learner wrote.
   * `owner_user_id` and `authorization_scope` are **required** arguments, and the cache scope is
     derived from them rather than from the decision service. The first version took the scope from the
     optional service, which meant a run whose service was absent fell back to one shared
     server-internal scope — user-b was served user-a's judgment from cache. The test
     `test_cache_scope_is_owner_scoped_and_never_crosses_users` reproduces exactly that and now pins
     it (two distinct owner scopes, and a repeat call by the same owner served from cache).
   * Consumers: `V3DomainAdapter._retrieve` attaches `jev_reference` (the report) to every returned
     source, and `QaService.stream` puts `referenceVerification` into the SSE `meta` event and the
     stored message metadata. A message that names no question label costs **zero** calls and reports
     `questioned: false` — no lookup, no transport, nothing to bill.

   Tests: `tests/test_jev_reference_verification.py` (29 — the module contract with an offline
   transport, including the negation residue `"it is not question 3, it is 4"`), the prose cases above
   in `tests/test_reference_parser.py`, and `tests/test_jev_reference_business_path.py` (4) which
   drives the real `context.retrieve` adapter over a document whose labels came from the real chunker
   and structure parser. Browser: journey 4 of `tests/e2e/jev-structured.spec.ts` drives the shipped QA
   page and reads the report out of that page's own `POST /api/qa/chat` stream.

   **Still not wired, with the original reasons intact:** the *document-side* surface
   `app/rag/structure.py::extract_structured_blocks`. There, a label is a metadata annotation with no
   per-field review slot in `problem_index_entries` and no consumer that would act on a review
   outcome, so wiring it would still be the "a helper exists" pattern this report refuses to count.
   The DeepSeek-Vision path (`ProblemSolutionOutput.question_transcription` / `conditions`) likewise
   remains generated natural-language text with no field/value/unit schema.



