# BRAND REPLACEMENT MATRIX (task A1)

**State of this document.** Round-44 scan, updated in round 72. Class A is now **done on both
runtimes**: the web app reads `apps/web/src/brand.ts` and the backend reads `app/brand.py`, and each
has a guard that fails when a visible old name comes back. What remains of Class A is the
operations material (`ops/`, scripts) and the historical documents, which stay old by decision
(§3). The measured scan result below is round 44's and is kept as the record of what was found.

**State of this document.** Round-44 scan, **updated in round 45 when the visible rename actually
happened for the web app and the agent service**. The scan method and the class split below are
unchanged; §2 and §5 now record what was converted, and §6 records what is honestly still old.

Target brand: **CourseJesus** / **耶课稣** / `coursejesus.com`, API hosts `rag.coursejesus.com`
and `agent.coursejesus.com`.

**Round-45 result, measured on the built artifacts rather than on the source:** the web app now
carries one brand source (`apps/web/src/brand.ts`), both HTML entries and the PWA manifest are
generated from it, and the shipped bundle contains **no** user-visible old-brand text — the only
remaining `CourseMate` strings are the compatibility identifiers (§3). The guard test
`apps/web/tests/brand.test.ts` fails if any file outside an explicit remainder list prints the old
name, so a new page cannot reintroduce it.

## 1. Where the old name actually is (measured)

Round-44 baseline, and the round-45 values after the visible rename:

| Pattern | Round 44 | Round 45 | Areas | Largest areas |
|---|---|---|---|---|
| `CourseMate` | 481 | 466 | 39 | `docs` 158, `apps/web` 90, `services/rag-api` 59, `archive` 41 |
| `coursemate` (lowercase) | 515 | 522 | 34 | `docs` 281, `archive` 43, several top-level reports |
| `COURSEMATE` (uppercase) | 62 | 62 | 20 | `docs` 27, reports, `scripts` 3, `apps/web` 3 |
| `qqttai` (current domain) | 169 | 169 | 17 | `docs` 100, `scripts` 34, `services/rag-api` 2 |
| `coursejesus` | 2 | 26 | — | the new brand source, tooling and documents |
| `耶课稣` | 0 | 6 | — | the brand source, the manifest/description and this document set |

The repo-wide totals barely move because most occurrences are history, identifiers and
compatibility names — which is exactly why the class split below, not the headline count, is the
actionable view. `apps/web` fell from 113 to 90: the visible strings are gone, and what remains
there is compatibility identifiers, code comments and test assertions.

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

**Missing asset, found by the scan:** `apps/web/public/manifest.json` **did not exist**, so there
was no PWA manifest to edit. Round 45 therefore *generated* one — `manifest.webmanifest`, emitted
at build time from the brand source with name/short_name/theme colour/icons — instead of patching a
file that was not there. `favicon` was already present and is reused as the interim icon.

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

| `coursemate-dev-verification-secret` (the dev fallback verification secret) | a credential *default*, not a brand string: renaming it invalidates locally issued verification tokens, and production requires `CMUI_VERIFICATION_SECRET` | recorded in `app/brand.py`, class B |
| `coursemate-ui-update` (a value in the UI service's status payload) | a machine value a client may key on | recorded in `app/brand.py`, class B |

### Class B is enforced, not only documented (round 72)

`app/brand.py` records these identifiers in `COMPATIBILITY_IDENTIFIERS`, and
`services/rag-api/tests/test_brand_identity.py` fails when an old-name identifier appears that
nobody recorded — that is how a careless rename slips in. Its first run found
`coursemate_internal_token`, the parameter name FastAPI derives the internal-token header from.

The **runtime** half is protected by the UI-extension suites: renaming `cmui_users` at a single use
site makes them fail with 6 failures and 16 errors
(`work/current-change/check-cmui-rename-detection.py`). A static check cannot prove that, which is
why this document does not claim it.
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
   help text **read it** instead of hard-coding. Implemented in round 45 as
   `apps/web/src/brand.ts`; the documents use `%BRAND_*%` placeholders that the Vite plugin
   substitutes, and a leftover placeholder fails the build.
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
* `docs` dominates the raw totals. Most of that is Class B history, which is why the
  *user-visible* list in §2/§3 is the actionable one — a "466 occurrences" headline would
  overstate the work and a "0 files changed" style report would understate it.
* Converted in round 45 and verified on the built artifacts: both documents, the manifest, the
  shell and pages, the legacy shell, and the agent service's prompt/log. The guard test in
  `apps/web/tests/brand.test.ts` enforces this for the web app and the agent service sources.
* **Still old in round 45, and listed rather than implied:** the operations scripts and `ops/`
  material (37 occurrences), the historical reports and `docs/` (Class B by decision, not by
  omission), and `services/rag-api`. The backend is **not** only compatibility names — it carries
  real identity strings, found while checking whether the rename could break a backend test:
  the FastAPI titles (`CourseMate RAG API`, `CourseMate UI Update API`), the Chinese teacher
  prompts in `app/cm_update/provider.py` (`你是 CourseMate 教师。…`, which shape generated teaching
  text), the default display name `CourseMate 同学`, two database-guard error messages, and the
  tutor prompt pinned by `tests/test_tutor_prompt.py` (`assert instructions.startswith("You are
  CourseMate")`). Converting those means changing the prompt and its test **together**, which is
  why it is a separate step rather than a side effect of the front-end pass. None of them is a web
  page, and all 41 tests covering them pass unchanged in round 45.
* **Notification/e-mail templates** the pack names are still to be written; they do not exist yet,
  so there is nothing to convert — the same source will feed them when they are created.
* **Logo:** `BRAND.logoStatus` is `PENDING_ASSET` in code, and the interim mark is the repository's
  existing `favicon.svg` — not the owner's artwork, and not presented as final.
