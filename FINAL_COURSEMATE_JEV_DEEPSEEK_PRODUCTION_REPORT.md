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

**Re-measured 2026-09-22 (rounds 31–37).** The rows below are current as of the frozen revision named
in the first row; where a number changed, the earlier value is kept beside it so the change is
auditable. One claim in the previous version of this table was **wrong** and is corrected in place: the
mypy row said "none in a file the current revision changed or added", and re-measuring showed the
opposite — the round-31 work had added seven errors of its own (`docs/recovery/CURRENT_BLOCKER_LEDGER.md`
B-10).

| Item | Value |
|---|---|
| Revision | `169bd57` (branch `fix/codex-dsh-audit-20260919`) — the revision the current gate ran on; supersedes `6e65396`, which superseded `b8104d9`/`5be2d0a` |
| Backend regression | **1293 passed / 0 failed** in 1577.08s (`work/current-change/full_run_round35.log`); `git diff 169bd57 -- services/rag-api benchmarks` is empty, so the run describes the committed revision. Previously **1235 passed / 0 failed** in 1467.07s on `6e65396` — the delta is +17 (QA + module-metric), +8 (split/calibration) and +33 (DeepSeek switch-window config guards) |
| Browser journeys | **46 / 46 in real Chrome against the real services**: `ui-refresh` 19, `jev-structured` 6, `coursemate` 4, `learning` 3, plus the isolated **`codex-audit` 14** (run on `d656bf7`; its own report records 14 expected / 0 unexpected / 0 flaky / 0 skipped) |
| Web app | `tsc --noEmit` 0, **73 unit tests** (19 files), production build 0 (was 68 tests) |
| agent-api | `tsc --noEmit` 0, **92 unit tests**, build 0 |
| Schema in source | RAG **30** (`LATEST_V3_SCHEMA_VERSION`), UI 13, Agent 1 |
| Ruff / mypy | ruff **1815 for `app` + `tests`, before and after** the later revisions, so no lint debt was added; whole-app mypy is **1004 errors in 32 files**, with **`app/jev/` and `app/evaluation/` at zero**. What remains is legacy `ui_extension`/`cm_update` debt (728 of the 1004 in `app/cm_update/app.py`), reported by rule rather than hidden. The earlier "1074 in 39" figure was the pre-correction measurement |

## 3. What the release would change in production

| Change | Detail |
|---|---|
| Backend code | the Jev semantic-decision layer (19 definitions, all in `shadow`), the six structured-enhancement modules, the single shared decision layer threaded through the orchestrator/UI extension/run endpoint/internal APIs, and the receipt, entity-relation and feedback-queue stores |
| Database | schema **25 → 30**: 026 learning-start events, 027 assessment preparation reference, 028 Jev decision receipts, 029 proposal-only entity relations, 030 the durable feedback queue. All additive — and now **measured rather than asserted**: the 25 → 30 rehearsal on a database built by the release's own code gives `old_rows_unchanged: true` (every fingerprinted table byte-identical before and after by SHA-256) with `integrity=ok`, `foreign_key_violations=0` and all 52 invariant counters at zero except the four expected seeds/backfills; and the rollback guard re-run against release `4ef5064` returns **`ROLLBACK_SAFE_WITH_MIGRATED_DB`** (the old release opens a schema-30 database with no missing or retyped columns and no narrowed CHECK enums), so a code-only rollback is viable. A missing 029 store still degrades to "nothing recorded" and a missing 030 store only means feedback cannot be queued |
| Generative path | **only if the owner supplies a DeepSeek key**: every generative role moves from Qwen/Model Studio to DeepSeek. Without the key the deployment keeps answering exactly as it does today |
| Semantic path | **only if the owner supplies a TypeSafe credential**: definitions can leave `shadow` for `advisory`/`on`, per definition, after the calibration gate. Without it every decision stays in `shadow` and the deterministic result remains user-visible |
| Frontend | the shell changes from the previous round's build (the "报告问题" entry, the citation-verdict marker, the reasoning-strength save fix). Netlify project `coursemate-ai-qqtt` (`qqttai.com`) |
| Not changed | DNS, the official CS3481/GE2324 trees, SRSZQ (`8.210.58.22`), any other host |

## 4. Production facts — re-verified read-only on 2026-09-22T01:59Z

Gathered live over SSH to the production host with read-only commands only (no writes,
no restarts, no secret values read — only variable *names*).

| Item | Verified value |
|---|---|
| Host / instance | `iZbp1f0vqhds2341pdqqiyZ` = instance `i-bp1f0vqhds2341pdqqiy`, region `cn-hangzhou`, uptime 15 days, 2 vCPU / 3.5 GB (2.5 GB available), disk 40 GB with **27 GB free** |
| Live release | `/srv/coursemate/current` → `/srv/coursemate/releases/4ef5064`, which is also the **newest** release directory (mtime 2026-09-21 01:46) |
| Services | `coursemate-rag` active (uvicorn 127.0.0.1:28000, started 2026-09-21 02:08 CST), `coursemate-agent` active (127.0.0.1:28001), `nginx` active (80/443), `coursemate-monitor` **unit failed** — see finding 2 |
| RAG database | `/srv/coursemate/data/releases/20260919T202006Z/rag.sqlite3`, schema **25**, `integrity_check=ok`, 20 courses (2 published), 67 documents, 1963 chunks, 16 workspaces, 44 knowledge nodes across `cs3481` + `ge2324` (the official trees are present and untouched) |
| Other stores | UI store 3,366,912 bytes (modified 2026-09-22 00:33); agent DB 32,768 bytes; uploads 119 MB; `/srv/coursemate/data` 255 MB |
| Backups | 10 snapshots, 1.3 GB, newest `20260921-four-changes-final-before-schema13` at 2026-09-21 01:58 — **32 hours old** |
| Protected env | `/etc/coursemate/{rag,agent,monitor}.env`, mode 640, `root:coursemate`. **No `JEV_*` or `TYPESAFE_*` variable exists yet**; model configuration names present are `V3_MODEL`, `OPENAI_CHAT_MODEL`, `AGENT_MODEL_NAME`, `OPENAI_EMBEDDING_MODEL` (values deliberately not read) |
| TLS | `qqttai.com` valid to 2026-11-10; `rag.`/`agent.qqttai.com` valid to 2026-12-12; the certbot renew timer is enabled and ran 5 h ago |
| Public endpoints | `qqttai.com` 200, `rag.qqttai.com/health` 200, `agent.qqttai.com/health` 200 (a status code, not an acceptance) |

### Three production findings that change the release plan

1. **The backend services are not boot-enabled.** `coursemate-rag.service` and
   `coursemate-agent.service` declare `WantedBy=multi-user.target` but are `disabled`, and
   `list-dependencies --reverse multi-user.target` confirms neither is boot-wired. They run only
   because they were started manually. A reboot would leave nginx (enabled) in front of nothing.
   **Required release step: `systemctl enable` both units** — a zero-downtime change, but a
   production change, so it belongs to the release window.
2. **The monitor is failing because backups are stale — correctly.** `coursemate-monitor` runs on a
   ~5-minute timer and exits non-zero when any check fails, so systemd shows the unit as `failed`.
   Its own log is the useful part: `rag` healthy, `agent` healthy, `disk` healthy, **`backup` failing
   ("latest backup is stale (191857s old)")** against `MAX_BACKUP_AGE_SECONDS=93600` (26 hours). The
   newest snapshot is 32 hours old because **there is no automatic CourseMate backup timer at all**
   (SRSZQ has one; CourseMate's snapshots are taken manually). The pre-release backup in the plan is
   therefore mandatory, and the owner should decide whether to add a backup timer so this check can
   ever pass unattended.
3. **Something else already listens locally** on 127.0.0.1:8080/8081 and nginx proxies to 18080/18081
   as well as 28000/28001. Those are not part of this release's path (the release only restarts
   rag/agent), but they are recorded so a later step does not mistake them for ours.

Everything else matches the previously recorded state, so the plan's assumptions hold — with the two
additions above.

## 5. What is verified locally (and therefore is not a production claim)

All of it is in `FINAL_COURSEMATE_JEV_STRUCTURED_ENHANCEMENT_REPORT.md` in detail. In
short: 12 case call sites reachable in the production wiring with the semantic layer in
`shadow`; all six structured modules wired with consumers (A, B, C, D, E, F + feedback);
shadow invariance proven byte-identical for the retrieval, evidence and citation paths;
the citation/evidence/conflict machinery deterministic where it can be and semantic only
where a real signal exists; the high-impact reference-solution gate in place; and the
browser journeys green against the real services in real Chrome.

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

1. **Re-verify production read-only** — done 2026-09-22T01:59Z (see §4). Confirmed on that pass: the
   old Singapore host is not serving CourseMate (the live host is the Hangzhou ECS above), SRSZQ has
   its own independent backup timer, and the official CS3481/GE2324 nodes are present and untouched.
   Re-run the same read-only script immediately before the release and compare.
2. **Live validation on the frozen revision** (needs the credentials): the DeepSeek canary across its
   roles, then the Jev canary and the calibration/ablation runs on the frozen splits, inside the
   printed budget ceiling. If a definition fails its gate it stays in `shadow` — that is a reportable
   outcome, not a failure to hide.
3. **Freeze the release**: build the backend artifact, run `verify_release_build.mjs` and the release
   preflight, and record the SHA.
4. **Consistent production backup** of all three databases, uploads, share snapshots and the current
   configuration, with the release SHA and schema version recorded alongside. This is not optional
   housekeeping: the newest existing snapshot is 32 hours old and the monitor is already failing on
   that (§4 finding 2).
5. **Isolated restore + migration rehearsal**: restore that fresh backup into a separate directory and
   run migrations 026–030 there, proving `integrity_check=ok`, `foreign_key_check` empty, and that the
   data survives.
6. **Real rollback check**: run the *actual* previous release (`4ef5064`) against the migrated database
   (`verify_rollback_compat.py`) and record the verdict.
7. **Deploy the immutable backend release** and point `current` at it; restart `coursemate-rag` /
   `coursemate-agent`; confirm a real request path, not just `health=200`.
8. **Enable both backend units for boot** (`systemctl enable coursemate-rag coursemate-agent`) — §4
   finding 1; without it the next reboot takes the site down.
9. **Owner places the credentials** in the protected env files only
   (`/etc/coursemate/rag.env`, `agent.env`), never in chat or Git.
10. **Production frontend build + publish** to `coursemate-ai-qqtt` (`netlify deploy --prod`).
11. **Real acceptance** with one real sign-in: the journeys in §8 below, on CS3481, GE2324, a private
    course and a shared course.
12. **Post-release backup and monitoring**: take a fresh backup so the monitor's backup check passes,
    confirm the monitor reports healthy after it, then the Git push and this report completed with the
    real rows.

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
backend regression, real-browser journeys over the shipped shell, honest
`INSUFFICIENT_SAMPLES` where no labels exist, **no module left without a call site**
(round 30 wired A to the query-side exact-locator surface and reversed the earlier
`MODULE_ONLY` decision with the reasoning and the reproduced defect on record), and
`shadow` everywhere until a credential and a calibration gate say otherwise. Nothing here
should be read as evidence that teaching quality improved: that requires the labelled live
run, which has not happened.
