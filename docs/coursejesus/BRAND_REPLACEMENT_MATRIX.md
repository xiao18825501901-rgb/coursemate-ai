# BRAND REPLACEMENT MATRIX (task A1)

**State of this document.** Produced in round 44 by
`work/current-change/scan_brand_surface.py` over the current work tree (HEAD `552e809`). It is a
**scan**, not a replacement: no user-visible string has been changed yet, and this file exists so
the replacement is done surface by surface instead of as a repository-wide byte replace, which the
pack explicitly forbids ("不要逐字节全仓 replace").

Target brand: **CourseJesus** / **耶课稣** / `coursejesus.com`, API hosts `rag.coursejesus.com`
and `agent.coursejesus.com`. Today `耶课稣` appears **0** times and `coursejesus` appears **2**
times (both inside the new CourseJesus tooling added this round), so every visible surface is
still to do.

## 1. Where the old name actually is (measured)

| Pattern | Occurrences | Areas | Largest areas |
|---|---|---|---|
| `CourseMate` | 481 | 38 | `docs` 150, `apps/web` 113, `services/rag-api` 59, `archive` 41 |
| `coursemate` (lowercase) | 515 | 32 | `docs` 275, `archive` 43, several top-level reports |
| `COURSEMATE` (uppercase) | 62 | 20 | `docs` 27, reports, `scripts` 3, `apps/web` 3 |
| `qqttai` (current domain) | 169 | 17 | `docs` 100, `scripts` 34, `services/rag-api` 2 |
| `coursejesus` | 2 | 1 | `scripts` (this round's tooling) |
| `耶课稣` | 0 | 0 | — |

**31 user-visible files** currently carry the old name. The heaviest are listed in §3.

## 2. Class A — must change (user-visible)

| Surface | Where | Why it must change |
|---|---|---|
| Page title / document head | `apps/web/index.html` (`<title>CourseMate AI</title>`) | browser tab, search results, share cards |
| Shell + layout copy | `apps/web/src/CourseMateUi.tsx` (17), `apps/web/src/ui/App.jsx` (13), `apps/web/src/main.ui.tsx` (7), `apps/web/src/components/Layout.tsx` (5) | the product name a user reads on every page |
| Page copy | `pages/QaPage.tsx` (4), `KnowledgeTrees.tsx` (3), `CourseSettingsPage.tsx` (3), `DocumentsPage.tsx` (3), `LearningPage.tsx` (3), `HomePage.tsx`, `TasksPage.tsx`, `AboutPage.tsx`, `ErrorBoundary.tsx`, `ProtectedRoute.tsx`, `LearningFiles.tsx`, `OverlayPublicationPanel.tsx`, `AdminPublicationPage.tsx`, `CourseCenterPage.tsx` | titles, empty states, errors, help text |
| Static server copy | `scripts/serve_web_dist.mjs` (3) | served local UI text |
| Agent-service user-visible strings | `services/agent-api/src/server.ts`, `services/agent-api/src/services/agent.ts`, `services/agent-api/src/tools/intent-gate.ts` | messages a user can see |
| Package metadata | `package.json` `"name": "coursemate-ai"`, `apps/web/package.json` `@coursemate/web`, `services/agent-api/package.json` `@coursemate/agent-api` | published identity, build logs, SBOMs |
| Notifications / templates / docs entry points | notification templates, README, help pages, current product docs | the pack lists these explicitly |
| Canonical / OpenGraph / sitemap | wherever `qqttai.com` is canonical today (`docs` 100 + `scripts` 34 occurrences) | domain migration, see `DOMAIN_AND_CLERK_MIGRATION.md` |

**Missing asset, found by the scan:** `apps/web/public/manifest.json` **does not exist**. The pack
requires `manifest name/short_name` to be updated, so a PWA manifest has to be *created* (name,
short_name, theme/background colour, icon set) rather than edited. `favicon` must be checked in
the same pass; the icon itself is `PENDING_ASSET` until the owner supplies artwork.

## 3. Class B — must survive (history, compatibility, identity)

These are deliberately **not** renamed. Renaming them would break history, runtime identity or
saved user data, which the pack forbids in the same sentence that requires the visible rename.

| Surface | Reason to keep | Evidence |
|---|---|---|
| DB tables/columns `cmui_*`, env `CMUI_*`, `window.CourseMateAuth` | internal compatibility contracts already in use | pack §4; call sites must be inventoried before any rename, and any change must be dual-named |
| `archive/**` (41 + 43 + 3 occurrences) | superseded Laya/CourseMate-era material kept on purpose | archived, not current source of truth |
| Migration files and their numbering | already applied in production; content is history | never rewritten |
| Audit hashes, `content_hash` values, frozen datasets | pinning evidence | changing them invalidates provenance |
| Existing `course/document/node/user/assessment` IDs | users' data and progress | production identity |
| Historical reports (`FINAL_*`, `DSH_*`, `COURSEMATE_V2_LEARNING_ATLAS_*`, `CHATGPT_REVIEW_*`) | they describe past states under the old name | superseded notes, not edits |
| Git commit messages, tags, release records | repository history | GitHub rename keeps them |
| Local source root `D:\CourseMate_COMPLETE_ARCHIVE_20260918\...` | the working tree must not move mid-flight | pack §5: no mid-round rename of the live cwd |

## 4. Class C — decide per case (ambiguous)

| Surface | Current | Options |
|---|---|---|
| File names carrying the brand, e.g. `apps/web/src/CourseMateUi.tsx` + `CourseMateUi.test.tsx` | 38 occurrences inside one component pair | rename files + imports in one commit, or leave the filename and change only strings. Strings are what users see; a rename must be import-safe |
| Playwright config names (`playwright.jev.config.ts`, 2 occurrences) | test-only identifiers | safe to change, but only with the reports that cite them |
| Internal log lines and code comments | non-user-visible | change opportunistically when the file is already being edited, not in a sweeping pass |
| Deployment/ops scripts referencing `qqttai.com` (34 in `scripts`) | mixed: some are canonical-URL definitions, some are history | split by whether the value is read at runtime |

## 5. Method (per the pack)

1. A single brand/URL configuration source provides English name, Chinese name, canonical origin,
   API origins, logo path and support name; front end, meta, manifest, notification templates and
   help text **read it** instead of hard-coding.
2. The visible rename and the domain migration are separate steps with separate evidence
   (`DOMAIN_AND_CLERK_MIGRATION.md`).
3. Every Class B entry gets an explicit compatibility note in this file when it is touched for
   another reason, so "we left it" is always a decision with a reason.
4. Logo: text-only brand until the owner supplies the asset; then validate the real file, clean
   the SVG, and generate the sizes/favicon/hashes. Until then the status is `PENDING_ASSET`, and
   a missing image never blocks the rest of the work.

## 6. Honest limits

* The counts above are line/occurrence counts from a text scan of tracked text files; they show
  where work is, not how many edits it will take.
* `docs` dominates the raw totals (150 + 275 + 27). Most of that is Class B history, which is why
  the *user-visible* list in §2/§3 is the actionable one — a "481 occurrences" headline would
  overstate the work and a "0 files changed" style report would understate it.
* No string has been replaced yet, so `BRAND_UI` remains **NOT_STARTED** in
  `COURSEJESUS_EXECUTION_STATE.md`. This file is the plan and the measured baseline.
