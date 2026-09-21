# TEMPLATE_V2_MIGRATION

Replacement of the teaching/exercise prompt set with the 16 V2 files delivered in this round,
without breaking the exercise runtime contract or the 题目/详解 prompts.

## 1. What was replaced, and what was deliberately not

| Role | Before | After |
|---|---|---|
| 14 professional teaching templates (01–14) | `*_V1.txt` registered by `app/cm_update/templates.py` | `*_V2.txt` from `template_text_v2/`, now the default |
| 做一题 (exercise content) | `EXERCISE_PROMPT_V1.txt` | `EXERCISE_PROMPT_V2.txt` |
| OTHER / cross-disciplinary | `15_OTHER_GENERAL_V1.txt` | `15_OTHER_GENERAL_V2.txt` |
| 题目 (problem answering) | `PROBLEM_PROMPT_V1.txt` | **unchanged** — not part of the 16-file replacement set |
| 详解 (step explanation) | `EXPLANATION_PROMPT_V1.txt` | **unchanged** |
| exercise.v2 runtime contract | `EXERCISE_RUNTIME_CONTRACT_V2.txt` + `exercise_contract.py` | **unchanged** — the hidden-answer/structured-output contract is not a content template |
| Plan writer / classification instructions | `PLAN_WRITER_INSTRUCTION_V1.txt`, `CLASSIFICATION_INSTRUCTION_V1.txt` | unchanged |

V1 files stay on disk so that a historical conversation keeps the template version it was
created with; nothing was deleted and no chat, node binding, grade or learning state was reset.

## 2. Integrity evidence (independently re-verified, not just reported)

Command: `python work/current-change/verify_template_v2.py` (compares the in-repo prompt files
against `TEMPLATE_V2_MANIFEST.json`, byte for byte, including a pack-copy comparison).

```
verified_hashes=16/16
problems: none
PROBLEM_PROMPT_V1.txt exists= True
EXPLANATION_PROMPT_V1.txt exists= True
EXERCISE_RUNTIME_CONTRACT_V2.txt exists= True
```

Test coverage: `tests/test_jev_deepseek_template_v2.py` — **21 passed**, asserting

* all 16 V2 bodies load with distinct body hashes matching the manifest;
* body lengths match the manifest `text_characters` (±2 trailing-whitespace tolerance);
* every professional template still carries the mandatory sections (`ciallo`, 中文, the final
  teaching step marker);
* `problem_prompt()` / `explanation_prompt()` are byte-identical to the V1 files (regression:
  they must never be silently replaced);
* `EXERCISE_RUNTIME_CONTRACT_V2.txt` still exists and `exercise_contract.parse_exercise_output`
  still parses a V2 payload **and** the V1 legacy marker.

## 3. Registry versioning

`app/cm_update/templates.py` now exposes a versioned registry:

* `registry(version="V2")` — default, the 16 V2 entries;
* `registry("V1")` — the previous set, still loadable for historical evidence;
* `template_body(template_id, version="V2")`, `other_template(version="V2")`,
  `exercise_prompt(version="V2")`;
* `problem_prompt()`, `explanation_prompt()`, `plan_writer_instruction()`,
  `exercise_runtime_contract()` keep their V1/contract files;
* `registry_json()` reports both versions (id, level, professional, version, file, body hash,
  file hash), so a template change is auditable by hash rather than by filename.

Existing call sites were not rewritten: the V2 default flows through the same function
signatures, so new requests use V2 while old conversations keep their recorded version.

## 4. Behaviour rules kept intact

* **First round shows only the question.** That is a display rule; the server still generates and
  stores the complete private reference answer through the `exercise.v2` structured contract
  (one generation, structured output validated before anything is shown). No separator-marker
  protocol was reintroduced.
* One 做一题 item may contain 3–6 sub-questions — that is a different quantity from the five
  assessment questions and the two flows stay separate.
* The runtime statement of the model identity says DeepSeek; the V2 texts mentioning
  Qwen/DeepSeek compatibility are retained as source material and do not trigger any Qwen call.

## 5. V1 integrity test — resolved (was a declared follow-up)

`tests/test_codex_template_integrity.py` hardcodes V1 body hashes and originally called
`template_body()`/`exercise_prompt()` without a version argument, so it failed against the new V2
default (16 failures). It was fixed by pinning **V1 explicitly** at every lookup — not by relaxing
the hashes:

```python
body = loaders[key]() if key in loaders else templates.template_body(key, V1)
loaders = {'EXERCISE': lambda: templates.exercise_prompt(V1), ...}
```

Rationale: that file's hashes are the Word-source parity contract for the 14 original bodies, and
V1 stays on disk byte-identical, so the original guarantee is preserved exactly. A new
`test_both_template_versions_are_served_side_by_side` asserts V1 and V2 both resolve, have the same
id set, and return different bodies/files — so the pin cannot silently start comparing V2 against
V1 hashes. V2 parity against `TEMPLATE_V2_MANIFEST.json` remains pinned hermetically in
`tests/test_jev_deepseek_template_v2.py`.

Result: `tests/test_codex_template_integrity.py` **22 passed** (was 17 failed / 21 tests).

## 6. Not run

* Visual/render validation of the V2 documents: **NOT_RUN** (the manifest states
  `visual_render_validation_performed_this_turn=false`).
* Live-model quality comparison of V1 vs V2 templates: **NOT_RUN** (no DeepSeek credentials or
  budget; would also require the A/B harness).
