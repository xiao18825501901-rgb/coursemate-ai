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

## Entity Relations — NOT OWNED YET

> **STUB — this half is unowned.** No workstream has claimed the entity-relations
> half of this document. It is intentionally left blank until an owner is assigned;
> nothing here should be read as a promise about entity resolution, alias handling,
> or a `CourseEntityResolution` module. Module B (entity alignment) is a separate
> workstream and will fill in this section.
