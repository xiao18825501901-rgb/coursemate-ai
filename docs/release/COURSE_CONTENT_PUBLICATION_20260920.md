# CourseMate official course content publication — 2026-09-20

## Decision and outcome

**Content publication outcome: ACCEPTED.**

**Whole-site functional outcome: PARTIAL FAILURE; see `FINAL_COURSEMATE_PRODUCTION_ACCEPTANCE.md`.**

The Owner authorization was received at approximately **2026-09-20 04:56:35 CST** (attachment creation timestamp). It explicitly authorizes all current platform-managed official/campus courses, including CS3481 and GE2324, for immediate publication after structural and source validation. The decision is recorded as `OWNER_APPROVED_FOR_PUBLICATION`; it is not represented as prior per-node human review of newly generated content.

Live inventory showed that no new content generation or publication transition was necessary. Both courses already had v3 PUBLISHED official trees, approved publication requests, immutable snapshots, and ACTIVE releases from 2026-09-18. The stale claim that CS3481 had zero published nodes was corrected from live data rather than used as an instruction to create a duplicate tree.

No application release, schema migration, DNS change, Netlify artifact, Clerk application, old-user qualification, seed fixture, or manual SQL publication occurred.

## Production identity

| Item | Verified value |
| --- | --- |
| Public site | `https://qqttai.com` |
| Application release | `aa3ffc250c2c4584f35dceea1a9ceec61123fdef` |
| Deployed release path | `/srv/coursemate/releases/aa3ffc2` |
| Netlify production deploy | `6aaef108d89499d9a5e52722` |
| Active host | `iZbp1f0vqhds2341pdqqiyZ` / `47.114.34.175` |
| Active data release | `/srv/coursemate/data/releases/20260919T202006Z` |
| RAG / UI / Agent | Schema 25 / 11 / 1 |
| Model used by production smoke | `qwen3.8-max`, Alibaba Model Studio compatible Responses protocol |
| Old Singapore writers | `coursemate-rag=inactive`, `coursemate-agent=inactive` on `iZt4n0k005125h6vlxoiloZ` |

At 2026-09-20 06:06 CST, the public site, RAG health, integrated UI-extension health, and Agent health each returned HTTP 200. On the active host, RAG, Agent, nginx, and `coursemate-monitor.timer` were active.

## Courses activated

| Course | Documents | PUBLISHED tree | Nodes | Atomic | Composite | Active published Specs | REQUIRED items | Template during smoke | Publication status |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| CS3481 | 38 | `official-tree-15fd76815c754d148064e5e8872ad35c` | 22 | 15 | 7 | 15 | 15 | `OTHER` runtime fallback | ACTIVE |
| GE2324 | 28 | `official-tree-168ad777b4a549debd6614d75c77a09d` | 21 | 14 | 7 | 14 | 15 | no global assignment; safe `OTHER` fallback | ACTIVE |

No other public official/campus course exists in the live database. The complete query results and validation boundaries are in `PRODUCTION_COURSE_CONTENT_INVENTORY.md`.

## Publication workflow evidence

### CS3481

- Approved request: `knowledge_publication_87071faf24204eb58ce5ac125aebf59d`
- Snapshot: `snapshot_b16adad434984878be20d7af3f70fc46`
- Active release: `release_cce007b525ae4994bbfa2c444886b2dd`
- Reviewer hash: `9814ec167915`
- Reviewed: 2026-09-18 12:58:53.821 UTC

### GE2324

- Approved request: `knowledge_publication_b1cf69762f7a490d9eba39907f298bbf`
- Snapshot: `snapshot_cff2eeac765241c9b57ff40326f64adb`
- Active release: `release_f7dce39f596747968e1cba0e9c76aa01`
- Reviewer hash: `9814ec167915`
- Reviewed: 2026-09-18 12:58:53.957 UTC

Each release was created by the normal request → immutable snapshot → independent review → approval → ACTIVE release workflow. Prior rejected requests remain in the audit trail. No status field was changed directly.

## Generation provenance and cost

The live model evidence shows the historical M6D4 generation that produced the current v3 tree lineage:

| Course | Provider / model | Completed calls | Input tokens | Output tokens | Official list-price estimate |
| --- | --- | ---: | ---: | ---: | ---: |
| CS3481 | Alibaba Model Studio / `qwen3.8-max` | 34 | 48,293 | 33,809 | USD 0.299440 |
| GE2324 | Alibaba Model Studio / `qwen3.8-max` | 36 | 53,666 | 37,109 | USD 0.329986 |
| Total historical generation |  | 70 | 101,959 | 70,918 | USD 0.629426 |

The evidence identifies the `responses` protocol, `ENDPOINT_WORKSPACE` region label, `M6D1_V1` template/schema, and COMPLETED status for all 70 calls. These calls occurred on 2026-09-17 and were not repeated in this activation run.

The official international Singapore list price used for the estimate is USD 2 per million non-cached input tokens and USD 6 per million output tokens. The provider invoice was not accessed, so promotion/free-quota effects are unknown and the estimates must not be described as charged invoice amounts. Source: <https://www.alibabacloud.com/help/en/model-studio/qwen3-8-max>.

The bounded production acceptance run used 17 model runs / 18 provider stages: 10 completed and 7 failed closed, 51,058 prompt tokens, 9,443 completion tokens, and 27,008 cached prompt tokens. At USD 0.25 per million cached input tokens, its list-price estimate is **USD 0.111510**. The failures are included because they can still be billable. No automatic unbounded retry occurred.

## Backups and integrity

### Pre-content recovery point

`/srv/coursemate/backups/pre-content-20260920/coursemate-v2-20260919T210125.093115Z`

### Post-content recovery point

`/srv/coursemate/backups/post-content-20260920/coursemate-v2-20260919T220317.614625Z`

The post-content backup was taken with both writer services stopped and restarted immediately afterward. It contains:

- RAG, Agent, and UI databases;
- 67 RAG upload files / 124,236,993 bytes;
- UI uploads archive;
- 16 share-snapshot files / 181,408 bytes;
- manifest, SQLite verification receipt, and SHA-256 manifest.

Every checksum passed. All three backup databases have `integrity_check=ok` and zero foreign-key violations. The backup size is 121,293,922 bytes. The same database integrity results are present in the pre-content recovery point.

An earlier backup wrapper attempt failed safely because the wrapper lacked its executable bit, and a direct system-Python attempt failed because Ubuntu 22.04 Python 3.10 does not provide `datetime.UTC`. No complete-looking backup was produced by either attempt. The successful backups used the deployed application Python 3.12 runtime.

## Official file repair

All 66 official source files matched the recorded size and SHA-256 in the active data release, but locked publication rows retained obsolete absolute paths under `/srv/coursemate/rag/uploads`. A transaction that attempted to rewrite those paths was rejected by the official-publication lock and rolled back.

The approved non-data compatibility repair is:

```text
/srv/coursemate/rag/uploads
  -> /srv/coursemate/data/releases/20260919T202006Z/uploads
```

Afterward all 66 paths resolved to the expected bytes; file preview worked and an original-file production download returned HTTP 200. The symlink is reversible. A future data release must retarget and revalidate it before switching traffic.

## Production acceptance performed

The production browser/API run used two short-lived Clerk identities, two issued seven-digit verification codes, public/synthetic text, and the live Qwen provider. Credentials and code values were kept out of artifacts and Git.

Verified behavior includes:

- campus gate before verification; redeemed verification persisted;
- student publication attempt denied with HTTP 403;
- six-item navigation and CS3481/GE2324 course pinning;
- official file list/search/32-page preview/original download;
- comments, direct messages, unread/read transition, and complete people search;
- real Task Agent create/update/delete;
- private-course isolation and frozen shared-course snapshot isolation;
- CS3481 22-node and GE2324 21-node published trees;
- distinct Learning Progress and Assessment values;
- CS3481 tree rendered with 15 clickable atomic nodes and 7 composite headings;
- first atomic-node open created a bound Pair and a real two-stage Thinking run;
- second open reused the Pair/history; page reload restored the Pair and both-pane state;
- Normal follow-up used Normal mode;
- user-entered Problem Mode produced a full solution parsed into four server steps;
- backend LearningBridge created a real teaching run and returned to the original step;
- pair/run/event APIs did not return `generated_prompt` or `PLAN_WRITER_INSTRUCTION`.

Evidence:

- `work/content-publication-20260920/production-content-acceptance.json`
- `work/content-publication-20260920/production-cs3481-tree-expanded.png`
- `work/content-publication-20260920/production-dual-pane-real-model.png`

The machine evidence contains 55 PASS checks, 2 FAIL checks, and 1 NOT_RUN check. It is correctly labeled `PARTIAL_FAILURE`.

## Cleanup

- Sixteen temporary private/share workspaces and 32 associated private courses were removed through a narrowly scoped cleanup; zero acceptance private courses remain.
- The two temporary Clerk users were deleted and are absent from a fresh seven-user Clerk directory listing.
- A supported complete directory sync retained inactive tombstones for the two local projections; both have `active=0`.
- Two official-course learning workspaces and their private shadow courses for the now-deleted synthetic owner remain because referentially restricted learning evidence has no supported archive/delete API. The attempted broad deletion rolled back. Foreign keys were not disabled and no audit evidence was hand-deleted. These rows are inaccessible through active identity resolution.
- UI learning history, runs, messages, and share audit rows under the inactive synthetic subject are likewise retained as inaccessible audit evidence.

## Remaining limitations

1. **“做一题” did not complete.** Three bounded attempts failed closed: two `INVALID_EXERCISE_BOUNDARY` and one `EMPTY_EXERCISE`. No answer steps or reveal record leaked. The current generic `EXERCISE_PROMPT_V1` conflicts with the private delimiter contract expected by the server parser.
2. **Problem-step knowledge buttons were not visible.** The server parsed four steps, and backend LearningBridge/return worked, but the browser rendered zero `.step-link` buttons. A normal problem answer is tagged as an exercise; `pages.jsx` clears `steps` on every exercise-tagged message before `RichText` renders it.
3. Because item 1 failed, “显示答案” and “详解” for the generated exercise were NOT_RUN.
4. Scoped professional classification was not stored for the synthetic course/user pairs; teaching correctly used the safe `OTHER` fallback. This is not a global template assignment.
5. The actual provider invoice was not queried; only an official list-price estimate is available.

The latest Owner prompt explicitly prohibited redeploying unchanged/stable application components. Therefore the two application defects were recorded and were not patched/deployed during this content-only run.
