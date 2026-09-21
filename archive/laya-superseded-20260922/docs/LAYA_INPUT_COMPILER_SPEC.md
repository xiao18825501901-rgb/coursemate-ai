# Laya Input Compiler — Spec & Report

**Workstream:** no silent truncation, full provenance for the Laya (`mmBERT-base`)
System-1 decision path.

**Files owned by this workstream**

| File | Role |
|---|---|
| `services/rag-api/app/laya/budget.py` | Token-budget accounting + faithful mirror of the official `build_sequence`/`render_options`/`serialize_state`. |
| `services/rag-api/app/laya/compiler.py` | `compile_decision(...)`, typed errors, policy, provenance, and the three builders. |
| `services/rag-api/app/laya/__init__.py` | Minimal package export (budget + compiler only). Created so the package imports; `adapter.py`/`models.py`/`errors.py` are deliberately not imported. |
| `services/rag-api/tests/test_laya_compiler.py` | 21 tests, including an independent transcription of the official algorithm. |
| `LAYA_INPUT_COMPILER_SPEC.md` | This document. |

`app/laya/adapter.py`, `app/laya/models.py`, `app/laya/errors.py` are owned by a
different workstream and are **not** created or imported here. No type is imported
from them: the compiler defines its own `TokenizerProtocol` and its own typed
errors, so it does not depend on files that have not landed yet.

---

## 1. What the compiler does

The official Laya pipeline (`work/laya-recon/rl_common.py::build_sequence`)
silently shortens inputs in four places:

1. **Per-option 48-token cut** — `[MASK] + tok(" " + opt)[:48]`.
2. **`opt_budget < 16` re-cut** — every option is re-cut to `per = max(4, (head_max_len - 16) // n_options)`; labels keep their names but lose their text (the Banking77 collapse: 77 labels → 0.425).
3. **Instruction/head cut** — `head_ids[:max(8, opt_budget)]`.
4. **State `room` cut** — `st[:room]` (default right-truncation), plus `ids[:max_len]` which can make a marker fall off the end so an option vanishes entirely (the official API then raises `ValueError("options do not fit in head_max_len")`).

`compile_decision(...)` reproduces the **exact** final `input_ids`/`markers` that
`build_sequence` would produce (same layout, so pre-flight equals production) while
recording, for each of the four points, whether content was actually cut. Before
emitting it checks those diagnostics and either:

* **(a) fits by construction** — a builder shortens only within its own documented
  per-field limits and marks `provenance.fit_by_construction = True`; or
* **(b) refuses** with `InputTooLongError(kind, detail)` / `InsufficientContextError(kind, detail)`.

It **never** emits a request whose options were re-cut to `per` while keeping their
names, and never silently drops an option, instruction, or state.

---

## 2. Tokenizer strategy — honest without the real model

* The tokenizer is **injectable** via `TokenizerProtocol` (a `typing.Protocol`):
  `__call__(text, add_special_tokens=False)["input_ids"]` plus `mask_token`,
  `mask_token_id`, `cls_token_id`, `sep_token_id`, `pad_token_id`.
* **Default / test stand-in:** `OfflineTokenizer` — a deterministic word/piece
  counter (runs of letters/digits are one piece, each other character is its own
  piece) with the **documented** mmBERT-base special ids from
  `work/laya-recon/ml_encoder_config.json`: `pad=0`, `cls=sep=eos=1`, `mask=4`,
  `vocab_size=256000`. Text-token ids are a deterministic CRC32-derived value ≥ 5
  so they can never collide with a special id.
* **Real adapter:** `AutoTokenizerAdapter` imports `transformers.AutoTokenizer`
  *inside* `__init__` and is constructed **only** when a local `model_dir` is
  passed (`AutoTokenizer.from_pretrained(model_dir)` — local, no Hub download). It
  also exposes `spans()` via `return_offsets_mapping=True` so retained-state char
  counts stay exact with the real tokenizer.

**Why this is honest without the real model present:** the only thing the budget
math depends on is the *token count* and the *placement of the four special ids*.
The stand-in reproduces both deterministically and exactly (special-token
placement is exact; token *count* is an approximation of the real tokenizer). The
compiler's guarantee — *"the emitted `input_ids`/`markers`/`input_tokens` equal the
official `build_sequence` output"* — is therefore a property of the algorithm, not
of any particular tokenizer: it holds for **every** tokenizer satisfying the
protocol, including the real `AutoTokenizer`. The equality test below proves it
for the stand-in; the adapter reuses the identical algorithm, so the property
transfers to production.

**Important:** `transformers`, `torch`, and `numpy` are **not installed** in the
`rag-api` venv and no model directory is present, so `AutoTokenizerAdapter` is
documentation-plus-code only — it is **not** exercised by the test suite. Nothing
here claims a real tokenizer or model was available.

---

## 3. Refusal taxonomy

| `kind` | Error type | Trigger | Default |
|---|---|---|---|
| `options` | `InputTooLongError` | `opt_budget < 16` (re-cut to `per`) | **always refuse** (never emit re-cut) |
| `options` | `InputTooLongError` | an option marker lands ≥ `max_len` (vanishes) | **always refuse** |
| `options` | `InputTooLongError` | `option_count > max_flat_options` (20) | refuse |
| `option` | `InputTooLongError` | any option text > 48 tokens | refuse (`truncate_options=False`) |
| `instructions` | `InputTooLongError` | head/instructions would be cut | refuse (`truncate_instructions=False`) |
| `state` | `InputTooLongError` | state would be cut by `room` | refuse (`truncate_state=False`) |
| `options` | `InsufficientContextError` | primitive has zero options | refuse |
| `state` | `InsufficientContextError` | state is empty | refuse |
| `plan` | `InsufficientContextError` | plan/hidden-answer key in state | refuse (`allow_plan_state=False`) |
| `state` | `InsufficientContextError` | key outside `ALLOWED_STATE_KEYS` | opt-in (`enforce_state_allowlist=False`) |
| `primitive` | `InsufficientContextError` | unknown primitive | refuse |

The three `truncate_*` policy flags, when set `True`, let the compiler apply the
**official** cut and mark it in provenance (`truncated_options` / `truncated_head`
/ `truncated_state`); they are never on by default. The `opt_budget < 16` re-cut is
a hard refusal even when `truncate_options=True`.

### `CompilePolicy` documented defaults

```python
max_flat_options: int = 20            # Banking77 collapse threshold
truncate_options: bool = False        # per-option 48-token cap
truncate_instructions: bool = False   # head/instructions cut
truncate_state: bool = False          # state room cut
allow_plan_state: bool = False        # plan/hidden-answer guard
enforce_state_allowlist: bool = False # allowlist enforcement (opt-in)
```

### Plan / hidden-answer leak guard

`compile_decision` scans dict state **recursively** for exact (case-insensitive)
keys in `PLAN_LIKE_STATE_KEYS` (`plan`, `answer`, `answer_key`, `hidden_answer`,
`solution`, `next_steps`, …) and refuses with `InsufficientContextError("plan", …)`
unless `allow_plan_state=True`. Matching is exact on the key, so the authorized
`student_answer` / `reference_solution` inputs of `assessment.criterion_review.v1`
are **not** matched. The documented allowlist `ALLOWED_STATE_KEYS` is the union of
`required_state` across the 12 catalog definitions (42 keys).

---

## 4. Provenance

`Provenance` is a dataclass with `as_dict()`, populated per decision:

`source_fragment_ids`, `char_ranges`, `page_ranges`, `content_hash` (SHA-256 of the
canonicalized inputs), `input_tokens`, `option_count`, `per_option_tokens` (the
text-token budget actually used per option), `options_complete`,
`retained_state_chars` (exact via tokenizer char offsets), `truncated_state` /
`truncated_head` / `truncated_options`, `head_budget` (`max(8, opt_budget)`),
`state_room`, `compiler_version`, `fit_by_construction`, `policy`, `decision_key`.

---

## 5. Builders (bounded, honest inputs by construction)

* **`build_single_local_relation(...)`** — one `choice` question, 2–6 options,
  each ≤ `max_option_chars` (160). Refuses (never truncates) an option above the
  per-field char limit.
* **`build_evidence_window(...)`** — keeps `question`, `conditions`, `negations`,
  `numbers`, `units` verbatim inside a conservative state budget
  (`max_len - head_max_len`), appends lower-priority fields only while they fit,
  and returns an `EvidenceWindow` recording exactly which fields were dropped.
  Refuses if a must-keep field alone does not fit.
* **`build_hierarchical_template_decision(...)`** — for the 14 professional
  templates: stage 1 chooses a coarse domain/level from a small candidate set
  (+`OTHER`), stage 2 chooses the template within that domain (+`OTHER`). "Cannot
  decide" returns `OTHER` instead of forcing a match; the full 14-template text is
  never sent as one flat question (a flat 14-long-text question triggers the re-cut
  refusal — see test).

---

## 6. Worked table — the 12 decision definitions

| # | key | primitive | candidate count | option-length policy | state policy | refusal condition |
|---|---|---|---|---|---|---|
| 1 | `intent.next_action.v1` | Choice | 8 (CONTINUE…OTHER) | flat, short catalog texts; refuse >48-token option | `message`, `fixed_anchor`, `current_mode`, `active_assessment` | re-cut / 48-cut / head / state / plan |
| 2 | `retrieval.support.v1` | Score | 5 levels (0–4) | score levels short | `query`, `exact_target`, `candidate_id`, `candidate_text`, `source_metadata` — `candidate_text` via evidence window | state room (long candidate) |
| 3 | `source.supports_claim.v1` | Noul | 2 (false/true) | fixed | `claim`, `source_span`, `source_version`, `task_scope` | state room / plan |
| 4 | `source.select_span.v1` | Choice | dynamic (span ids) + `NO_SUPPORT` | short span ids; refuse if any >48 | `claim`, `candidate_spans` | too many spans (re-cut) / state |
| 5 | `context.keep_segment.v1` | Noul | 2 | fixed | `segment`, `current_task`, `fixed_anchor`, `remaining_scope` — `segment` via evidence window | state room |
| 6 | `pedagogy.next_method.v1` | Choice | 6 | flat, short | `learner_request`, `known_prior_evidence`, `topic`, `template_profile`, `current_step` | re-cut / 48-cut / state |
| 7 | `coverage.item_support.v1` | Choice | 4 | flat, short | `saved_delivery`, `required_item`, `valid_spans`, `node_spec_version` — delivery via evidence window | state room |
| 8 | `assessment.criterion_review.v1` | Choice | 4 | flat, short | `frozen_question`, `frozen_rubric_criterion`, `reference_solution`, `student_answer`, `deterministic_verification`, `candidate_answer_spans` — long fields via evidence window | state room |
| 9 | `template.match.v1` | Choice | 14 + `OTHER` | **hierarchical** (never flat 14) | `course_title`, `curriculum_samples`, `materials_revision`, `known_course_level` | flat-14 re-cut refusal |
| 10 | `exercise.prototype.v1` | Choice | dynamic + `NONE` | short prototype ids | `node`, `eligible_prototypes`, `recent_exposures`, `learning_evidence` | too many prototypes (re-cut) |
| 11 | `graph.prerequisite.v1` | Choice | dynamic + `NONE` | short node ids | `current_node`, `error`, `allowed_predecessor_nodes` | too many predecessors (re-cut) |
| 12 | `corpus.quality.v1` | Score | 4 levels (0–3) | score levels short | `document_fragment`, `source_metadata`, `parse_flags` — fragment via evidence window | state room (long fragment) |

---

## 7. How the equality property is asserted

`tests/test_laya_compiler.py` contains an **independent** transcription of
`render_options` / `serialize_state` / `build_sequence` from
`work/laya-recon/rl_common.py` (behaviorally verbatim; the `%` string formatting
is modernized to f-strings, which produce byte-identical strings). Two tests use it:

1. `test_mirror_matches_reference_on_all_cases` — `app.laya.budget.build_sequence`
   equals the reference `(input_ids, markers)` on *fits* and *truncating* cases
   (48-cut, re-cut, head cut, state cut, vanish), proving the mirror is faithful
   even in the exact regimes the compiler refuses.
2. `test_compiler_equality_property` — for every "fits" case, the compiler's
   `decision.input_ids`, `decision.markers`, and `decision.input_tokens` equal the
   reference `ref_build_sequence(...)[0]` / `[1]` / `len(...)`. This is the
   strongest available proof that pre-flight numbers equal production.

Because the tokenizer is injected, the same algorithm (and therefore the same
equality) holds for the real `AutoTokenizer` in production.

---

## 8. Verification results

```
$ .venv\Scripts\python.exe -m pytest tests/test_laya_compiler.py -q
.....................                                                    [100%]
21 passed in 0.21s

$ .venv\Scripts\ruff.exe check app/laya/budget.py app/laya/compiler.py app/laya/__init__.py tests/test_laya_compiler.py
All checks passed!
```

---

## 9. What is real vs. offline stand-in

* **Real:** the official algorithm's control flow and layout (transcribed
  line-by-line), the documented mmBERT-base special-token ids (`pad=0`,
  `cls=sep=eos=1`, `mask=4`, `vocab_size=256000`), and the budget config
  (`max_len=1024`, `head_max_len=256` from `ml_rl_agent_config.json`).
* **Offline stand-in:** token *counts* (a deterministic word/piece counter) and
  text-token ids (CRC32-derived, non-special). These are approximations of the real
  tokenizer and are **never** used to serve a checkpoint.

## 10. Not done / limitations

* `AutoTokenizerAdapter` is not constructed or tested (no `transformers`, no model
  directory). It must be verified against a real checkpoint before serving.
* The 14 professional templates' actual texts/domains are "dynamic" (not present
  in this repo), so `build_hierarchical_template_decision` is generic over a
  supplied `list[TemplateOption]`; the business callsite supplies the mapping.
* `app/laya/__init__.py` was created (outside the strictly-listed deliverables)
  because the package must be importable; it imports only `budget` and `compiler`.
