# Learning Loop Live Acceptance

Date: 2026-09-28

## Acceptance matrix

| Layer | Status | Evidence |
|---|---|---|
| Reference package | **PASS** | 172 isolated tests; not production evidence. |
| Repository backend integration | **PASS** | RAG combination: 66 passed, 1 upstream Starlette deprecation warning. Agent: 100 passed; typecheck/build passed. |
| Repository web integration | **PASS** | 31 test files, 143 tests passed; TypeScript and production build passed. |
| Real browser against isolated integrated services | **PASS** | 15/15 Playwright tests passed in 2.6 minutes. Includes async evaluation/evidence card, N>=5, panes/history, Task Agent, sharing/isolation, multi-file input, mobile and long course name. |
| Database migration/recovery | **PASS** | Production schemas RAG 60 / UI 15 / Agent 2; all three `integrity_check=ok`, foreign-key violations 0. Post-deploy isolated restore passed. |
| Live-model learning-loop quality | **NOT VERIFIED** | This feature release made no new paid DeepSeek/Jev call. Existing providers remain configured and healthy, but no result is relabeled as this feature's live-model acceptance. |
| Production public runtime | **PASS (signed-out/public scope)** | `coursejesus.com` HTTP 200; release SHA `420d205...`; one Login/Register action; zero console warnings/errors and zero >=400 responses. RAG/UI-extension/Agent health all 200. |
| Production authenticated student cycle | **NOT VERIFIED** | No real Clerk student session/test account was provided, and the release did not impersonate a user or inject synthetic production rows. |
| Student outcome / D7 | **NOT MATURE** | No eligible real cycle exists yet; no uplift claim is made. |

## Defects found during browser acceptance

1. The asynchronous poll called `getExercise` without importing it. The polling loop caught the
   resulting exception, so the database completed evaluation while the UI stayed pending. Added the
   import plus a regression test that observes `PENDING -> GRADED` projection.
2. React StrictMode can unmount/remount the same class instance in development. `unmounted` is now
   reset in `componentDidMount`, covered by a regression test.
3. A legacy browser assertion expected a single-file picker. The shipped product intentionally
   supports multi-file upload; the assertion now verifies `FileList` multi-selection.
4. Signed-out startup previously probed `/me` before Clerk was loaded. The UI now waits for Clerk
   and does not call protected session APIs without a token.

## Production records

- Backend immutable release: `8e01781e18d6fc86c431ffe17c372712b6ec27b2`.
- Frontend application release: `420d20522ed2aff33759f5dc13a4231963e9e85c`.
- Netlify production deploy: `6ab9ab09cd69077bf7e9a4da`.
- Netlify preview deploy: `6ab9aab4acb181b96caba611` (static artifact check only; production
  Clerk keys are domain-bound, so preview is not an authentication acceptance environment).
- Production receipt: `/srv/coursemate/backups/frontend-learning-loop-420d205-6ab9ab09cd69077bf7e9a4da.txt`.
- Screenshot: `docs/learning-loop/evidence/production-signed-out-420d205.png`.

## Cost boundary

No new paid model request was issued for this integration/deployment. Therefore this report records
feature model spend as **not incurred**, not as proof that future requests cost zero. Monetary
business metrics remain `UNKNOWN` until an authoritative amount ledger is connected; provider usage
and unknown outcomes retain their existing receipts.
