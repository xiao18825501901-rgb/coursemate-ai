# FINAL_COURSEMATE_JEV_DEEPSEEK_PRODUCTION_REPORT

> **Status: release candidate, NOT a production acceptance report.**
> Nothing below has been deployed. Every production row is `NOT_RUN` because the
> live gate is blocked on owner-provided credentials (`MINIMAL_OWNER_ACTION_CARD.md`).
> The local evidence is complete and was produced on one frozen revision; the release
> has not started, so no production claim is made anywhere in this document.

---

## 1. What this report is

The production companion to `FINAL_COURSEMATE_JEV_STRUCTURED_ENHANCEMENT_REPORT.md`.
It states (a) exactly what is verified locally and on which revision, (b) what the
release would change in production, (c) what is still unverified, and (d) the ordered
release plan with its rollback. Anything that has not happened is marked `NOT_RUN`.

## 2. Frozen revision and its evidence

| Item | Value |
|---|---|
| Revision | `b8104d9` (branch `fix/codex-dsh-audit-20260919`) |
| Backend regression | **1189 passed / 0 failed** in 1471.55s (`work/current-change/full_run_round27.log`) |
| Browser journeys | 28 / 28 in real Chrome against the real three services (ui-refresh 19, jev-structured 2, coursemate 4, learning 3) |
| Web app | `tsc --noEmit` 0, 68 unit tests, production build 0 |
| agent-api | `tsc --noEmit` 0, 92 unit tests, build 0 |
| Schema in source | RAG **29** (`LATEST_V3_SCHEMA_VERSION`), UI 13, Agent 1 |
| Ruff / mypy | clean on every touched file; whole-app mypy reports 1068 **pre-existing** errors in legacy `ui_extension`/`cm_update` code (the Jev layer has 6, all pre-existing) |

## 3. What the release would change in production

| Change | Detail |
|---|---|
| Backend code | the Jev semantic-decision layer (19 definitions, all in `shadow`), the six structured-enhancement modules, the single shared decision layer threaded through the orchestrator/UI extension/run endpoint/internal APIs, and the receipt/entity-relation stores |
| Database | schema **25 → 29**: 026 learning-start events, 027 assessment preparation reference, 028 Jev decision receipts, 029 proposal-only entity relations. All additive; a release rolled back after the migration still runs (verified by the rollback-compatibility guard and by the property that a missing 029 store degrades to "nothing recorded") |
| Generative path | **only if the owner supplies a DeepSeek key**: every generative role moves from Qwen/Model Studio to DeepSeek. Without the key the deployment keeps answering exactly as it does today |
| Semantic path | **only if the owner supplies a TypeSafe credential**: definitions can leave `shadow` for `advisory`/`on`, per definition, after the calibration gate. Without it every decision stays in `shadow` and the deterministic result remains user-visible |
| Frontend | the shell changes from the previous round's build (the "报告问题" entry, the citation-verdict marker, the reasoning-strength save fix). Netlify project `coursemate-ai-qqtt` (`qqttai.com`) |
| Not changed | DNS, the official CS3481/GE2324 trees, SRSZQ (`8.210.58.22`), any other host |

## 4. Production facts (read-only, recorded in an earlier round — re-verify before the release)

The task requires re-confirming these immediately before the production steps; they are
listed here as the starting point, not as a substitute for that check.

| Item | Value as recorded |
|---|---|
| Web | `qqttai.com`, Netlify project `coursemate-ai-qqtt`, deploy `6ab02278b7fae664934df25d`, branch `main`, authenticated CLI as the project owner |
| Services | `rag.qqttai.com` / `agent.qqttai.com` → ECS `47.114.34.175` (instance `i-bp1f0vqhds2341pdqqiy`, cn-hangzhou-k, 2 vCPU / 3 GiB) |
| Live release | `/srv/coursemate/releases/4ef5064`; `coursemate-rag` (uvicorn 127.0.0.1:28000), `coursemate-agent` (node 127.0.0.1:28001), nginx in front |
| Live data | RAG DB `/srv/coursemate/data/releases/20260919T202006Z/rag.sqlite3` at schema **25**, `integrity_check=ok`; UI store ~3.3 MB; uploads ~119 MB; backups ~1.3 GB under `/srv/coursemate/backups` |
| Env | `/etc/coursemate/{rag,agent,monitor}.env`, mode 640, `root:coursemate` (no secret is printed in any report) |
| Model config today | Qwen/Model Studio (`V3_MODEL=qwen3.8-max`, `AGENT_MODEL_NAME=qwen3.8-max`, `OPENAI_CHAT_MODEL=qwen3.7-plus`), embeddings `text-embedding-v4` |

## 5. What is verified locally (and therefore is not a production claim)

All of it is in `FINAL_COURSEMATE_JEV_STRUCTURED_ENHANCEMENT_REPORT.md` in detail. In
short: 12 case call sites reachable in the production wiring with the semantic layer in
`shadow`; six structured modules wired with consumers (B, C, D, E, F + feedback) or
`MODULE_ONLY` by an investigated decision (A); shadow invariance proven byte-identical
for the retrieval, evidence and citation paths; the citation/evidence/conflict machinery
deterministic where it can be and semantic only where a real signal exists; the
high-impact reference-solution gate in place; and 28 browser journeys green against the
real services in real Chrome.

## 6. What is NOT verified (every one of these is `NOT_RUN`)

| Item | Why |
|---|---|
| `JEV_LIVE_VALIDATION` | no TypeSafe credential in this environment |
| `DEEPSEEK_LIVE_VALIDATION` | no DeepSeek key in this environment |
| `CALIBRATION` / `ABLATION` results | require the live runs above; the offline harness is tagged `NON_INTERPRETABLE_PLUMBING_ONLY` and refuses a quality verdict |
| Five module component metrics | the frozen 310-sample dataset contains **no** labelled samples for `extraction.field_grounded.v1`, `entity.relation.v1`, `evidence.consistency.v1`, `teaching.capability.v1`, `tool.intent.v1`; their arms report `INSUFFICIENT_SAMPLES` and emit no number. Adding samples would change the frozen dataset hash and split manifest, which this project preserves deliberately |
| Any promotion out of `shadow` | depends on the calibration gate; nothing was promoted and no threshold was invented |
| `PRODUCTION_DEPLOYMENT` | not started — requires the release window and the owner's go-ahead |
| `PRODUCTION_ACCEPTANCE` | not started — requires one real sign-in and the release |
| Post-release monitoring / backup | not started |

## 7. Release plan (ordered; every step has a rollback)

1. **Re-verify production read-only** (the §4 table) and confirm the previous Singapore
   writer is stopped, SRSZQ is untouched, and the official CS3481/GE2324 trees are not
   regenerated.
2. **Live validation on the frozen revision** (needs the credentials): the DeepSeek
   canary across its roles, then the Jev canary and the calibration/ablation runs on the
   frozen splits, inside the printed budget ceiling. If a definition fails its gate it
   stays in `shadow` — that is a reportable outcome, not a failure to hide.
3. **Freeze the release**: build the backend artifact, run `verify_release_build.mjs`
   and the release preflight, and record the SHA.
4. **Consistent production backup** of all three databases, uploads, share snapshots and
   the current configuration, with the release SHA and schema version recorded alongside.
5. **Isolated restore + migration rehearsal**: restore the backup into a separate
   directory and run migrations 026–029 there, proving `integrity_check=ok`,
   `foreign_key_check` empty, and that the data survives.
6. **Real rollback check**: run the *actual* previous release (`4ef5064`) against the
   migrated database (`verify_rollback_compat.py`) and record the verdict.
7. **Deploy the immutable backend release** and point `current` at it; restart
   `coursemate-rag` / `coursemate-agent`; confirm health and a real request path, not just
   `health=200`.
8. **Owner places the credentials** in the protected env files only
   (`/etc/coursemate/rag.env`, `agent.env`), never in chat or Git.
9. **Production frontend build + publish** to `coursemate-ai-qqtt` (`netlify deploy --prod`).
10. **Real acceptance** with one real sign-in: the journeys in §8 below, on CS3481, GE2324,
    a private course and a shared course.
11. **Post-release backup and monitoring**, then the Git push and this report completed
    with the real rows.

Rollback: re-point `current` to the previous release (migrations are additive, so it can
read the migrated database — the case `verify_rollback_compat.py` checks); if data is
wrong, restore the pre-migration backup, which is the only path that discards rows and
therefore needs the owner's explicit decision.

## 8. Production acceptance journeys (to be executed, not yet)

File upload → retrieval → relevance/conflict reasoning → DeepSeek teaching → citation
verification → LEARNING → coverage → five-question assessment → text answer → image
answer → grading → raw score → step explanation → node result → history. Plus the
adversarial set: a Chinese alias finding English material, same-word-different-meaning
not merged, an exact question number never replaced by semantics, a wrong citation never
marked supported, Normal/Thinking never mis-selected, an unrevealed answer never exposed,
a wrong side-effecting tool call blocked, a legitimate explicit tool call not
over-blocked, a private cache never crossing users, and safe degradation when the
semantic layer is unreachable.

## 9. Honest summary

The system is **release-ready locally and unverified in production**. The value of this
round is that the local state is real and reproducible — one frozen revision, a full
backend regression, 28 real-browser journeys, honest `INSUFFICIENT_SAMPLES` where no
labels exist, `MODULE_ONLY` where no call site exists, and `shadow` everywhere until a
credential and a calibration gate say otherwise. Nothing here should be read as evidence
that teaching quality improved: that requires the labelled live run, which has not
happened.
