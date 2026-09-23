# FINAL COURSEJESUS RELEASE REPORT

**Status: release candidate — NOT RELEASED.** This report records what the CourseJesus work
(brand/domain, Canvas private import, campus material) has actually delivered and verified as of
the revision named below. **Nothing in it has been applied to production:** the production release is
still `4ef5064` on schema 25, DNS has not been changed, and no production database, service or
setting has been touched. A report titled "final" is not a claim that a release happened; the release
sequence in §5 is where that would be recorded, and it has not started.

| | |
|---|---|
| Branch | `fix/codex-dsh-audit-20260919` |
| Revision this report describes | `705606f` (plus `6ae61e8` for the ledger note) |
| Commits ahead of `origin` | 109, **nothing pushed** |
| Full backend gate on `705606f` | **1548 passed / 3 skipped / 0 failed** in 2391.45 s, exit 0 (`work/current-change/full_run_round73.log`) |
| `mypy app --ignore-missing-imports` | 1004 errors / 32 files — the frozen baseline, unchanged through round 73 |
| Web | 21 test files / 90 tests passing; `tsc -b` and the production build clean |
| Real Chrome | **21/21** `ui-refresh` journeys passing (`work/current-change/ui_refresh_round70.log`) |
| Production | untouched and read-only throughout |

## 1. Brand and domain (T1)

* One brand source per runtime — `apps/web/src/brand.ts` and `services/rag-api/app/brand.py` — with
  the English name, Chinese name, canonical and API origins, logo path/status and support name.
* Visible surfaces read it: both HTML entries, the generated PWA manifest (which did not exist
  before), 17 front-end files, the agent service, the tutor persona a student's answers come from,
  the Chinese teacher instruction, the default display name in four use sites, both FastAPI titles,
  the recovery docstrings, the console messages and the CLI help.
* Guards: `apps/web/tests/brand.test.ts` (8) and `services/rag-api/tests/test_brand_identity.py`
  (11, structural — it reads literals from the AST, and refuses an old-name identifier nobody
  recorded; it found `coursemate_internal_token` on its first run).
* **Kept on purpose, each with a recorded reason:** DB tables/columns `cmui_*`, env `CMUI_*`,
  `window.CourseMateAuth/Math/Ui/App`, the internal token header, the `coursemate_*` version names,
  the deployment paths and systemd units, the `COURSEMATE_API_PROXY` variable, the `coursemate-v2-*`
  backup prefix, the monitor user-agent, the synthetic Clerk user's name, and the historical `m6f_*`
  admin-walk payloads.
* **Not done, and why:** the logo is `PENDING_ASSET` (no artwork was supplied — the interim mark is
  the repository's existing SVG, not presented as final); the GitHub repository rename, the domain,
  DNS, TLS, Clerk production settings and Netlify are **owner/platform actions** with the procedure
  written but not executed; notification/e-mail templates do not exist yet.

## 2. Canvas private import (T2)

Implemented and verified against a **simulated** school — no school has been contacted:

* `CanvasReadAdapter`: GET-only, exact-pattern endpoint allow-list, token only in the
  `Authorization` header, per-hop download validation with a token-free client, per-connection
  isolation. Security guards proven by mutation.
* OAuth: one-time state bound to (subject, institution), consumed on success and failure; the
  exchange and refresh against the documented endpoints; serialised per-connection refresh;
  revocation that clears the local credential even when the school endpoint fails.
* Credential storage: AES-256-GCM with a key id, bound to the connection, in files outside the
  database; **with no key the integration reports itself unconfigured rather than storing anything
  in the clear**, and the job row has no token column at all.
* The worker imports a selection end to end through the real `IngestionService` into a real private
  course, with the frozen 12-state machine, per-file checkpoints, and the failure rules the pack
  fixed (no retry on `403`, honour `Retry-After`, end the batch on an expired token, stop at a
  checkpoint on cancel without deleting material, and never report a job with unfinished files as
  complete).
* Nine HTTP routes and the wizard: both "从 Canvas 导入" entry points are real underlined buttons,
  and the screen a real user sees today reads **"学校连接尚未开通"** with the reason per school and the
  local-upload fallback. **There is no personal-access-token input anywhere.**
* **Blocked:** the school Developer Key. Until it exists the status stays `NOT_CONFIGURED`, and the
  connect/select/progress steps are covered by the route tests and unit tests rather than by a
  browser.

## 3. Campus course expansion (T3)

* Scan: 1919 manifest rows reconciled against disk — 0 missing, 0 size mismatches, 0 unlisted,
  8,868,856,230 bytes (8.26 GiB), streamed SHA-256, committed with personal filenames redacted.
* Plan: every file decided — **1479 `INGESTABLE`, 186 `DOWNLOAD_ONLY`, 254 `BLOCKED`** across 34
  offerings, 28 with ingestable material. One consolidated review list of **1715 rows** is written
  from the committed inventory, so no personal filename enters Git.
* Ingested: 社会实践 (`628`, CityU (DG)) through the real `IngestionService` into a **private** campus
  course — 1 document, 2 chunks, `visibility=private`, `publication_status=private`,
  `published_at=NULL`. Nothing was published, and this path cannot publish.
* **Blocked on the owner:** the rights decision for the 1715 listed rows. Until it is made, every
  campus course stays private; the remaining 27 offerings run the same two commands once it is.
* **Not done:** campus display/verification wiring, and any publication.

## 4. What this work explicitly did not do

No Laya dependency, no Qwen fallback, no model-generated teaching text written by a semantic layer,
no Jev-driven permission decision, no fabricated acceptance (no fake OAuth, no shadow receipt, no
`health=200` treated as evidence), no unbounded publication of announcements, scholarship, grades or
restricted material, no reset or force-push, and no second writer created.

## 5. Release sequence and its current position

`local final green → live model validation → freeze release → production consistent backup →
isolated restore → migration rehearsal → real rollback release check → immutable backend →
protected env → production frontend build → Netlify → real users → post backup → monitoring → Git
push → final report`

Position: **step 1 is green on `705606f`; step 2 has not started** because it needs owner-supplied
credentials and an approved budget. Steps 3–16 have not started. The migration and rollback plan that
steps 8–9 will follow is in `docs/coursejesus/DATA_MIGRATION_AND_ROLLBACK.md`.

## 6. Honest limits of this report

* Every Canvas and campus statement above rests on simulated schools and local files. No real school
  authorisation has ever been performed, and no campus material has ever been published.
* The production figures quoted anywhere in this pack are **read-only observations** from an earlier
  round, not this round's measurements.
* "1548 passed" is the backend suite on one revision; it says nothing about model quality, which is
  what the live gate exists to measure.
* The two remaining owner-blocked external conditions (school Developer Key, Logo artwork) and the
  two decisions (material rights, production window) are the only things standing between this
  candidate and a real release; they are listed, with the exact action each one needs, in
  `OWNER_ACTIONS_ONLY_COURSEJESUS.md`.
