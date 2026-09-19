# Final CourseMate production acceptance

**Assessment time:** 2026-09-20 06:07 CST

**Application release assessed:** `aa3ffc250c2c4584f35dceea1a9ceec61123fdef`

**Netlify production deploy:** `6aaef108d89499d9a5e52722`

**Public site:** <https://qqttai.com>

## Final verdict

```text
OFFICIAL / CAMPUS COURSE CONTENT: PRODUCTION ACCEPTED
COURSEMATE FULL CONTENT + FUNCTION PRODUCTION ACCEPTED: NO
OVERALL: PARTIAL FAILURE
```

All current official/campus course content is live and valid. CS3481 and GE2324 each have one active PUBLISHED official tree, all current ATOMIC nodes have published Teaching Specs with REQUIRED coverage, published sources are official-course-only, and the production browser displays the real CS3481 tree.

The Owner's stated full-success standard is not met because the production “做一题” flow fails closed and ordinary Problem solutions suppress the clickable per-step knowledge buttons in the browser. Consequently generated-exercise answer reveal and detailed explanation could not be accepted. These are user-facing learning-workflow defects, not documentation gaps.

## Acceptance matrix

| Area | Result | Production evidence |
| --- | --- | --- |
| Public frontend / RAG / integrated UI / Agent health | PASS | Four public HTTPS GETs returned 200; active-host services and monitor timer active |
| Official course inventory | PASS | Exactly CS3481 and GE2324; private/workspace/shared courses excluded |
| CS3481 content | PASS | PUBLISHED v3; 22 nodes, 15 atomic, 15 published Specs |
| GE2324 content | PASS | PUBLISHED v3; 21 nodes, 14 atomic, 14 published Specs |
| Publication workflow and audit | PASS | Approved request, immutable snapshot, reviewer, ACTIVE release for each course |
| Source scope / private-data boundary | PASS | Official-only snapshot resources; no private/workspace source; no fixture markers |
| Tree structure | PASS | No parent/prerequisite cycles, cross-course references, or orphan atomic members |
| Dashboard and six-item navigation | PASS | Browser check |
| Campus/private/shared courses | PASS | Course pinning plus private and shared isolation checks |
| Files list/search/preview/download | PASS | 38-file CS3481 result, 32-page preview, byte-exact 1,095,540-byte download |
| Discussion | PASS | Persisted comment and deletion |
| Inbox / people / DM | PASS | Full directory search, DM unread/read |
| Share / receive / join snapshot | PASS | READY/imported copy remained frozen after sender source deletion |
| Calendar / Task Agent | PASS | Real create/update/delete |
| Student verification / campus gate | PASS | Gate before redeem, seven-digit redemption, persisted verification |
| Admin publication boundary | PASS | Student publication request returned 403 |
| Knowledge tree browser | PASS | 15 clickable atomic nodes, 7 composite headings |
| Learning Progress vs Assessment | PASS | Separate values across both published trees |
| First-node Thinking | PASS | Bound Pair and real two-stage `qwen3.8-max` run |
| Repeat-node and refresh persistence | PASS | Same Pair/run restored after reopen and reload |
| Normal teaching | PASS | Live completed Normal-mode follow-up |
| Unified dual-pane history | PASS | Pair/history restored; both panes retained server state |
| Internal plan confidentiality | PASS WITH BOUNDARY | Pair, run, event, history, and browser payloads exclude stored plan fields; no claim of mathematical non-extractability |
| User-entered Problem full solution | PASS | Completed run; server parsed four steps |
| “做一题” generation | **FAIL** | Three bounded live attempts ended `INVALID_EXERCISE_BOUNDARY`, `EMPTY_EXERCISE`, `INVALID_EXERCISE_BOUNDARY`; no answer leaked |
| “显示答案” / “详解” | **NOT RUN** | Blocked by failed exercise generation |
| Per-step knowledge buttons in Problem pane | **FAIL** | Four server steps, zero visible `.step-link` buttons |
| Backend LearningBridge and return | PASS | Real bridge teaching run completed and return position restored |
| Short-lived identity cleanup | PASS WITH RETAINED AUDIT | Clerk users absent; local directory tombstones inactive; referentially restricted learning evidence retained and inaccessible |
| Pre/post recovery points | PASS | All artifact hashes pass; three DBs integrity ok / FK 0 |
| Old Singapore writer isolation | PASS | RAG and Agent inactive on old host |

## Accepted course state

| Course | PUBLISHED tree | Nodes | Atomic | Composite | Published Specs | REQUIRED items | Active release |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| CS3481 | `official-tree-15fd76815c754d148064e5e8872ad35c` | 22 | 15 | 7 | 15 | 15 | `release_cce007b525ae4994bbfa2c444886b2dd` |
| GE2324 | `official-tree-168ad777b4a549debd6614d75c77a09d` | 21 | 14 | 7 | 14 | 15 | `release_f7dce39f596747968e1cba0e9c76aa01` |

The live database has no additional public official/campus course. The stale historical statement `CS3481 = 0 published nodes` is superseded by this read-only production inventory.

## Real model evidence and cost

- Historical official-tree generation: 70 completed `qwen3.8-max` calls, 101,959 input tokens, 70,918 output tokens; official-list estimate USD 0.629426.
- This production acceptance: 17 runs / 18 stages, 51,058 prompt tokens, 9,443 completion tokens, including 27,008 cached input tokens; official-list estimate USD 0.111510.
- Actual charged amount is UNKNOWN because billing-console/invoice data was not accessed; a free quota or promotion may reduce it.
- No new bulk course-content generation call was made in this activation run.

Official price reference: <https://www.alibabacloud.com/help/en/model-studio/qwen3-8-max>.

## Failure analysis

### 1. Generated exercise contract

`EXERCISE_PROMPT_V1.txt` is a broad teaching/exercise prompt that tells the model not to expose an answer on the first response. The server simultaneously expects exactly one private `【标准答案】` delimiter and rejects an empty or missing private answer. Live Qwen output did not reliably meet that combined contract. The parser behaved safely: it buffered private output, rejected invalid boundaries, persisted no exercise, and exposed no answer.

Required next-release fix: give exercise generation a dedicated concise structured contract, preserve fail-closed parsing, add streaming-boundary regression tests, and perform one bounded live canary before deployment.

### 2. Hidden Problem step buttons

The server correctly parsed an ordinary Problem answer into four steps. The UI then treated the message as an exercise and passed `{...m, steps: []}` into `RichText`, intentionally suppressing the bridge buttons for every exercise-tagged message. This conflates a user-submitted full solution with a generated diagnostic exercise.

Required next-release fix: distinguish diagnostic exercises from ordinary Problem solutions, or suppress `steps` only while a generated diagnostic answer is unrevealed. Add a browser regression that asserts visible step buttons and follows one through LearningBridge and back.

No fix was deployed in this content-only activation because the Owner instruction explicitly prohibited redeploying the stable application during this run.

## Security, data, and cleanup disposition

- No private course or workspace was published.
- No seed/fixture tree entered production content.
- No API key, prompt, email, or student record appears in published node/spec content.
- Internal plan bodies are absent from normal application payloads tested in production.
- Two temporary Clerk users are absent from a fresh Clerk directory fetch; their local projections are inactive.
- Referentially restricted synthetic learning history remains as inaccessible audit data. Foreign keys were not disabled and no manual destructive cleanup was attempted.
- The official-file compatibility link is reversible and points only to the active release upload root.
- Both recovery points remain intact; no rollback backup was deleted.

## Recovery points

- Pre-content: `/srv/coursemate/backups/pre-content-20260920/coursemate-v2-20260919T210125.093115Z`
- Post-content: `/srv/coursemate/backups/post-content-20260920/coursemate-v2-20260919T220317.614625Z`

Both contain RAG, Agent, and UI databases plus upload/share archives, manifest, hashes, and verification receipt. Every checksum passed; every database reports `integrity_check=ok` and zero foreign-key violations.

## Release gate

Content publication can remain live. No rollback is indicated for the official knowledge trees.

Do not label the whole product `COURSEMATE FULL CONTENT + FUNCTION PRODUCTION ACCEPTED` until a new application candidate fixes and production-verifies both defects above. A valid final rerun must at minimum prove:

1. one CS3481 “做一题” completes with a hidden answer;
2. “显示答案” reveals the saved steps;
3. at least one “详解” window completes;
4. an ordinary Problem solution displays per-step knowledge buttons;
5. clicking a button opens real LearningBridge teaching and returns to the original step;
6. plan fields remain absent, and backups/integrity/old-writer isolation remain healthy.

This report deliberately stops at `PARTIAL FAILURE`; it does not convert fail-closed behavior into a functional PASS.
