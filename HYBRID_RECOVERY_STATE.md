# HYBRID_RECOVERY_STATE

Round: CourseJesus P0 · OpenJev + deterministic checks + isolated DeepSeek dual
review (`hybrid-strict-v1`).  This file records the *actual* root, versions,
modules reused and modules added.  It is a state record, not an acceptance
report; the acceptance reports are the other six documents.

## 1. Real work tree (not a snapshot)

```text
REPO                D:\CourseMate_COMPLETE_ARCHIVE_20260918\01_SOURCE_REPOSITORY
                    \work\auto-knowledge-map-20260927\candidate
branch              feature/learning-loop-20260928
HEAD at start       51e2f3f87368e1b36db1b6329e7da4b0dc52fbe7   (= DOC in the handoff)
application base    916b76ce0534e4ce50a589521b0b618850df6956   (= parent of 51e2f3f)
working tree        clean except untracked artifacts/ and apps/web/public/downloads/
```

`git log` confirms `51e2f3f` is the direct child of `916b76c`, and the handoff's
`DOC` value matches this tree exactly.  Nothing was reset, stashed, cleaned or
force-pushed; the pre-existing untracked artifacts produced by the earlier
rounds are left in place.

## 2. Production facts re-read this round (not copied from the reports)

| Fact | Observed value | Source |
|---|---|---|
| current backend release symlink | `/srv/coursemate/releases/916b76c` | SSH to `coursemate-prod-new` |
| RAG runtime | `/srv/coursemate/runtime/rag-e0980c8/bin/python`, uvicorn `127.0.0.1:28000` | `systemctl cat coursemate-rag` |
| RAG env | `/etc/coursemate/rag.2d11587.env` + `secrets/p5-e0980c8.env` + `secrets/p0-openjev-916b76c.env` | `systemctl cat` |
| configured model role | `V3_MODEL=deepseek-flash`, `V3_MODEL_BASE_URL=https://api.deepseek.com` | `rag.2d11587.env` |
| database | `/srv/coursemate/data/releases/20260919T202006Z/rag.sqlite3` | `rag.2d11587.env` |
| schema | `schema_migrations` 64 rows, `LATEST_V3_SCHEMA_VERSION = 64` | read-only SQLite probe |
| integrity | `integrity_check=ok`, 0 foreign-key violations, 146 tables | read-only probe |
| content | 87 courses, 850 documents, 22 909 chunks, 50 learning workspaces | read-only probe |
| question pool | 49 `VALIDATED`/`AI_REVIEWED`, 9 `NEEDS_REVIEW`/`MODEL_ONLY` | read-only probe |
| provenance | 49 `READY` (`VALIDATION_COMPLETE_AI_REVIEWED`), 9 `NEEDS_REVIEW` | read-only probe |
| assessments | 11 `FROZEN` configurations; preparations 4 `READY` / 7 `BLOCKED` | read-only probe |
| SQL cold pool | `assessment-config-9636c4a8…` and `…-f8f05005…`, both `BLOCKED`, `prepared_slots=0`, `total_slots=5` | read-only probe |
| JEV receipts | 117 rows, all `model_version = "jev-latest"` (the retired TypeSafe SDK path), none from OpenJev | read-only probe |
| OpenJev service | `coursejesus-openjev.service` active, 1 418 148 KB RSS, loopback `127.0.0.1:28765`, `/ready` → `{"status":"ready","saturated":false}` | SSH |
| OpenJev model | `onnx-community/open-jev-deberta-v3-large-ONNX` @ `7c79f25b…`, `dtype=q4`, `maxLength=512`, `maxStateTokens=256` | model manifest on host |
| disk headroom | `/dev/nvme0n1p3` 40 G, 34 G used, **3.8 G free (90 %)** | `df -h` |
| Map50 | 13 over-limit trees stay paused; no Map50 unit was started this round | `AUTO_KNOWLEDGE_MAP_LEGACY_BACKFILL_ENABLED=false` |

## 3. Reused, unchanged

* `app/jev/*` — the gateway, catalog, receipt store and `SemanticDecisionService`
  are reused as-is.  The historical `jev_decision_receipts` table, its rows and
  its decoding are untouched, and the 117 `jev-latest` receipts keep their own
  identity.  They are **not** relabelled as hybrid reviews.
* `app/learning/question_validator.py` — the six deterministic hard gates and the
  four semantic dimensions are unchanged in meaning; the only change is that a
  signal may now name the `hybrid` reviewed path in addition to `jev`.
* `app/learning/question_persistence.py` — the single atomic `BEGIN IMMEDIATE`
  publication transaction, the append-only provenance triggers and the
  `_readiness` reason vocabulary are unchanged.
* `app/learning/orchestrator.py` — the configured-assessment preparation job,
  its lease, progress projection and `COMPATIBLE_POOL_COMPLETE` recovery receipt
  are unchanged.
* `app/cm_update/*` — the do-one run/SSE/GET recovery, the paired-pane guard and
  the persisted Assessment worker are unchanged.
* TypeSafe remains retired: no `TYPESAFE_*` construction, no fallback, not
  restored.

## 4. Added this round

| File | Purpose |
|---|---|
| `services/rag-api/app/learning/hybrid_review.py` | policy constants, case mapping, strict judge contract, reference verification, conjunctive combination, frozen balanced order, method identity |
| `services/rag-api/app/learning/deepseek_reviewer.py` | the two isolated reviewer roles, their blinded contexts and their recorded runs |
| `services/rag-api/app/learning/hybrid_quality.py` | orchestration, durable receipts, qualification records and the scope re-check |
| `services/rag-api/app/learning/hybrid_qualification.py` | held-out evaluation metrics, release-level false-accept/reject, exact binomial bound, scoped decision |
| `services/rag-api/app/learning/hybrid_evaluation_set.py` | positive controls plus recorded defect injection; a mutation that cannot apply produces no row |
| `services/rag-api/app/learning/openjev_observer.py` | advisory-only local observation; no field that grants or vetoes a decision |
| `services/rag-api/app/learning/prompts/judge_evidence_audit_v1.md` | reviewer A instructions (mirrors the supplied role prompt) |
| `services/rag-api/app/learning/prompts/judge_adversarial_audit_v1.md` | reviewer B instructions |
| `services/rag-api/migrations/065_hybrid_quality_review.sql` | additive tables + append-only triggers |
| `services/rag-api/scripts/run_hybrid_qualification.py` | the qualification CLI |
| `services/rag-api/tests/test_hybrid_review_policy.py` | policy contracts |
| `services/rag-api/tests/test_hybrid_publication.py` | end-to-end publication contracts |
| `services/rag-api/tests/test_hybrid_qualification.py` | metric and provenance contracts |
| `work/hybrid-p0-20260929/*` | read-only production probes and the OpenJev diagnostic |

## 5. Configuration surface

```text
HYBRID_QUALITY_ENABLED            default false  (new)
HYBRID_REVIEW_MAX_OUTPUT_TOKENS   default 4000   (new, 500..8000)
```

`HYBRID_QUALITY_ENABLED` unset means the Question Engine behaves exactly as
before: the six hard gates, the local/TypeSafe receipt chain and the
`QUESTION_REVIEW_UNAVAILABLE` refusal are all unchanged.  Enabling it is an
explicit billable decision — the two reviewer calls per candidate are real
provider requests.  The four `question.*` OpenJev definition modes stay as the
deployment sets them and are *not* a publication condition under this policy.

## 6. Round status labels

| Label | Status |
|---|---|
| `LOCAL_RUNTIME_REUSED` | **ACHIEVED** — one pinned q4 process, loopback bearer auth, caps unchanged, not restarted |
| `OPENJEV_DIAGNOSTICS_COMPLETE` | **ACHIEVED** — artifact recomputed and the input-contract defect reproduced live |
| `OPENJEV_ADVISORY_SCOPE` | **ACHIEVED** — advisory-only observer, no field that grants or vetoes |
| `DETERMINISTIC_CHECKS` | **ACHIEVED** — six hard gates unchanged, never overridable |
| `DEEPSEEK_REVIEW_A_B` | **ACHIEVED (live)** — two isolated roles, distinct response ids, references verified |
| `HYBRID_SCOPED_QUALIFICATION` | **NOT ESTABLISHED** — five measured runs; run 4 recorded a qualification on a thin sample, run 5 refuted it on 67 rows, and the raised floors now make run 4 non-qualifying.  Production holds no qualification row. |
| `CAMPUS_EXERCISE_RESTORED` | **NOT ACHIEVED** — nothing publishable |
| `PRIVATE_EXERCISE_RESTORED` | **NOT ACHIEVED** — nothing publishable |
| `SQL_COLD_POOL_GRADED` | **NOT ACHIEVED** — both configurations remain `BLOCKED` at 0/5 |
| `N8_ASSESSMENT_GRADED` | **NOT ACHIEVED** |
| `NORMAL_TEACHING_PRESERVED` | **PRESERVED** — source untouched, regression suite green |
| `AUTHENTICATED_BROWSER_ACCEPTANCE` | **NOT ACHIEVED** — see the acceptance document |
| `PRODUCTION_DEPLOYED` | **unchanged** — `916b76c` remains in service; the candidate is verified but not cut over |
| `QUALITY_NONINFERIORITY_EVIDENCE` | **UNKNOWN** — no paired same-sample gold exists |
| `MAP50_13_PAUSED` | **PAUSED** — unchanged |

The binding blocker is one case: `question.ambiguity.v1` is required by every
question, and this reviewer configuration does **not detect it** — three
different defect designs across four runs give catch rates of 2/3, 1/1 and 0/3,
with run 6 releasing all three under-specified items.  A corpus diagnosis also
showed why the earlier run produced no rows at all: every authored NUMERIC item
states its givens in prose, with zero digits in the stem, so the digit-based
mutation had nothing to remove.  The detailed measurements, the run-4/run-5
demonstration that a thin clean sample cannot be trusted, and the 14 %
provider-failure rate observed in run 6 are all in
`HYBRID_QUALIFICATION_AND_REGRESSION.md`.

The conclusion is that the remaining work is a **task-shape** change for the
ambiguity case -- enumerate the data and conventions the answer depends on, mark
each as stated or unstated, and derive the verdict server-side -- not another
prompt wording change.  That is recorded as the next action in §6 of that
document.

## 7. Explicitly paused / not done

* The 13 Map50 over-limit trees remain paused.  No Map50 unit was started.
* No student-facing data was rewritten: no grade, exposure, draft, submission or
  in-progress Assessment version was modified.
* TypeSafe is not restored; Laya/Qwen teaching providers and the GPU host are not
  touched.
* The candidate release was **not** cut over.  The reasons are in
  `HYBRID_PRODUCTION_RELEASE_AND_ROLLBACK.md` §4: the qualification failed, the
  release plan's own stop condition applies, and disk headroom was at the
  documented limit.
* The Clerk management API was deliberately not re-probed.

## 8. Commit

`8b84f94` — *feat(question-engine): hybrid-strict-v1 semantic gate with two
isolated DeepSeek reviewers*, on `feature/learning-loop-20260928`, directly on
top of `51e2f3f` / `916b76c`.  The pre-existing untracked `artifacts/` and
`apps/web/public/downloads/` from earlier rounds are left untouched.
