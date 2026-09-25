# CourseJesus P5 release ledger

Updated: 2026-09-25

P5 began on branch `fix/codex-dsh-audit-20260919` from documentation HEAD
`81d8d4002d585ddbfdb33432b4e48047d6ec6e3c` and tested P4 application revision
`df8694b0b4d97347f1c75baaca70c7e725e94a6e`. The current application candidate is
`0b06d69eb9f231e0774923ef8161af727b9bf652`; the working tree contains this ledger only. A P4
local result is never promoted to a live-model, human-review or production result.

## Current production reality (read-only observation)

Observed 2026-09-25 through the existing SSH aliases and unauthenticated public endpoints; secret
values and user content were not read or printed.

| Surface | Observed fact | Consequence |
|---|---|---|
| Public web | `qqttai.com` returned HTTP 200 with the title `CourseMate 学习空间`; `coursejesus.com`, `www.coursejesus.com`, `rag.coursejesus.com` and `agent.coursejesus.com` did not resolve to a usable public service | CourseJesus is **not deployed** on its intended public domain |
| Candidate ECS alias | `coursemate-prod-current` (`47.237.179.69`) has Caddy but no active CourseMate RAG/Agent services and no usable immutable release target | It is not the current application runtime |
| Running ECS alias | `coursemate-prod-new` (`47.114.34.175`) runs immutable path `/srv/coursemate/releases/4ef5064` behind nginx; RAG and Agent are active | This is the observed CourseMate runtime, not the P5 candidate |
| Model/config | RAG and Agent identify `qwen3.8-max` through the Singapore Model Studio compatible endpoint; `JEV_DEFINITION_MODES` is unset and no TypeSafe credential is present | The current runtime cannot satisfy P5 DeepSeek/Jev gates |
| RAG data | database integrity `ok`, zero foreign-key failures, schema 25, 20 courses, 67 documents, 16 workspaces | Must be restored to an isolated directory and migrated from the actual schema 25; no migration has run on production |
| UI data | integrity `ok`, zero foreign-key failures, UI schema 13, 20 users and 13 exercises | Must be included in the same consistent recovery unit |
| Agent data | integrity `ok`, zero foreign-key failures, one registered migration, 0 tasks | Third database exists and must be included even though it is currently small |
| Monitoring | RAG/Agent checks pass; disk has about 28.8 GB free; `coursemate-monitor` fails because the newest recognized backup is about 5.4 days old | Fresh verified backup and restored rehearsal are release blockers, not optional housekeeping |

## Release items

| Item | Existing evidence | Current gap | Next action | Close condition |
|---|---|---|---|---|
| P4 frozen candidate | Historical P4 evidence: 1818 backend passed/2 environmental skips; Web 115; Agent 92; five local Chrome suites; synthetic backup/restore and schema 25→38 rehearsal | P5 application/migration code changed, so those counts remain historical | Run targeted tests during implementation, then one necessary final regression/build/browser set on the frozen P5 SHA | New SHA and its own saved results are linked; P4 artifacts remain unchanged |
| Four required Jev signals | Catalog, validator and durable receipt/hash checks exist for ambiguity, answer agreement, MCQ distractors and rule violations | Deployment default and current production are `shadow`; no P5 live `on` receipts exist | Use an isolated run with exactly the required signal modes enabled; retain positive and adverse results | Exact durable `on` receipts produce `CLEAR`, `AGREE`, `ACCEPTABLE` and `SUPPORTED`; adverse/missing/mismatched inputs fail closed |
| C1–C4 Question Engine live cases | Full actual pipeline and offline deterministic-provider contracts exist | No live DeepSeek author/blind chain and no live specialized Jev quality evidence for this candidate | Add one bounded, fail-closed P5 runner around the real provider, Jev gateway and persistence path, then run the finite cases | Evidence-bound author→blind→hard gates→required receipts→READY succeeds without private-answer leakage |
| C5 empty-pool assessment | Offline five-slot backend/browser contracts pass | No live five-author/five-blind/five-slot preparation, real scoring journey or real vision answer path | Run only after C1–C4 and the single spend ledger are healthy | Five distinct READY families freeze at 10/15/20/25/30; text and real image submissions pass the existing assessment path |
| C6 recovery | Deterministic fault-injection tests cover missing receipts, partial slots, cancellation, duplicate input and restart | The paid live path must not be used to manufacture failures | Reuse deterministic injection for the failure matrix and preserve live provider failures if any occur naturally | Completed slots are reused, unknown upstream calls stay unknown, no paid retry is automatic |
| Practice metering | Commits `cd161f5`, `b714ed0` and `7abf94e` meter hint/feedback roles and make the shared model ledger accept either learning or practice operations | Needs final wide regression on frozen candidate | Keep targeted mounted integration evidence, then include in final regression | Every paid practice interaction has one durable reservation/run; replay does not bill again |
| Uncertain operation recovery | Commit `b8e77f0` adds read-only inventory, explicit evidence-based reconciliation and immutable retry links | Not exercised against production; no claim that an unknown provider result can be queried | Run on isolated fault fixtures; later inventory a drained restored snapshot read-only | Active work is untouched; complete/never-sent/failed/unknown states remain distinct; old IDs are never reused |
| Human content quality | Existing older general DeepSeek canary material is AI-reviewed only | No human decision exists for the exact P5 question revisions | Generate one private review card from the bounded C1–C5 artifacts | Owner/authorized human records PASS/REVISE/REJECT against exact case/revision/card hashes |
| Recovery unit | `backup_v2.py`/`restore_v2.py` cover RAG, Agent and UI databases, uploads, UI/assessment attachments and share snapshots | Historical backups do not contain P5 release identity and have not restored current production | Commit `0b06d69` adds a strict non-secret `release-config.json`; produce and restore a fresh drained snapshot | Manifest, hashes, byte counts, SQLite integrity/foreign keys, cross-store references and release-config identity pass in a fresh directory |
| Schema migration | P4 synthetic schema 25→38 passed; P5 migration 039 adds practice metering/reconciliation integrity and a 038→39 replay mapping | Current production is actual schema 25; no current snapshot has reached schema 39 | Restore production snapshot to isolation, migrate 25→39 and repeat initialize | Versions 1–39, expected objects, identities/data and repeated author/blind plus practice reservations remain valid |
| Old-release runtime rollback | Static compatibility tool is historical supporting evidence only | Release `4ef5064` has not run its own initialization/read-write path against a schema-39 copy | Export the actual runtime and start it only against a disposable migrated copy | Old init does not destructively replay superseded rebuilds; representative reads/writes and schema/data comparison pass, or rollback is explicitly downgraded |
| Paid-call authorization | Latest project authorization records `owner_authorized_unlimited_for_this_workflow`; protected local DeepSeek and TypeSafe keys exist | Unlimited authorization is not unlimited evaluation: the exact finite P5 call plan, output cap and stop conditions still need to be frozen | Preflight one bounded run; no automatic retry, model switch, recharge or new cloud resource | Every attempt and unknown usage stays in one append-only ledger; execution stops at the planned case/call limits |
| Production release | Earlier owner authorization allows required writes/deploy work, but the P5 sequence itself keeps model, human, snapshot and rollback gates | Human review, real snapshot migration and old-runtime rollback are not complete; current monitoring is red | Prepare immutable release/config/build identities while the gates run | Exact release package is recoverable; all earlier gates pass; public domain, real login and post-release monitoring are verified |
| Campus expansion | Frozen 1,921-file batch; growth fail-closed; 0 published | 1,715 rights decisions remain pending | Keep expansion paused; do not rescan either Canvas root | Withheld content remains unpublished and does not block Question Engine code release |

## Status boundary

- `SOURCE_IMPLEMENTED`: practice metering, uncertain-operation recovery, migration 039 and strict
  recovery metadata are committed through `0b06d69`.
- `LOCAL_VERIFIED`: related targeted suites passed (39 recovery/practice tests and 48
  backup/recovery tests); Linux-only backup tests remained 7 honest skips in that targeted run.
- `LIVE_DEEPSEEK_QUESTION_ENGINE`: **NOT RUN for P5**.
- `LIVE_JEV_BASE_SIGNALS` / `LIVE_JEV_SPECIALIZED_SIGNALS`: **NOT RUN for P5**.
- `HUMAN_CONTENT_REVIEW`: **NOT RUN**.
- `PRODUCTION_SNAPSHOT_RESTORED`, `MIGRATION39_RUNTIME_VERIFIED`,
  `ROLLBACK_RUNTIME_VERIFIED`: **NOT RUN**.
- `PRODUCTION_DEPLOYED`, `SIGNED_IN_STUDENT_ACCEPTANCE`,
  `POST_RELEASE_BACKUP_AND_MONITORING`: **NOT RUN**.
- `CAMPUS_EXPANSION_PAUSED`: **ENFORCED**.
