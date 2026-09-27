# CANVAS LOCAL BRIDGE

The second way into a school, and the one that exists while an institution has not issued a Developer
Key. The product revision is explicit about the shape:

> 正式多用户生产采用 OAuth；PAT 仅保留为本地/开发桥接。

So there are two routes, and they are not interchangeable:

| | OAuth | Local bridge |
|---|---|---|
| Who it is for | every user, in production | a school with no Developer Key yet; the owner's own migration; development |
| Where the credential lives | the school's token, encrypted by this service under `CANVAS_CREDENTIAL_KEY`, bound to a connection | **only on the user's own machine** — hidden input and process memory until the current run ends |
| What CourseJesus receives | the authorisation code, then API responses through its own adapter | course metadata, file bytes, receipts |
| Where the import runs | this service's worker | the user's machine downloads from Canvas, then uploads here |
| Entry in the UI | the primary `连接 Canvas` button | behind `无法连接？查看本地 Token 导入方式` |

**The token never reaches CourseJesus.** That is not a promise in this document; it is enforced in
four places:

1. **The schema has nowhere to put one.** `canvas_local_sessions` (migration 033) stores a *hash* of
   the one-time code and a description of the claim; there is no token, secret or credential column,
   and a test reads `PRAGMA table_info` to prove it.
2. **The request models refuse it.** Every body model sets `extra="forbid"`, so a bridge that posts
   `token`, `pat` or `personal_access_token` gets a `422` instead of having the value quietly
   ignored. The file upload is `multipart/form-data` with a fixed field list — there is no field a
   token could travel in.
3. **The page has no field for one.** `scripts/scan_web_bundle_for_pat.mjs` runs on every web build
   and fails it if the built output *or* the sources contain an input named like a token, a
   `localStorage`/`sessionStorage` write of one, or if the notice "本站不接收个人访问令牌" has
   disappeared. Its negative control is a planted `<input name="canvas_token" />` that it catches.
4. **The tutorial says so.** The Account → Settings → Approved Integrations → + New Access Token steps
   are shown, followed by: *"为了保护你的 Canvas 凭据，请不要把这个 Token 粘贴到 CourseJesus 网页。
   本地导入工具会通过隐藏输入读取 Token，只在当前进程内存中使用，关闭后不会保留。"*

## The flow

```
CourseJesus (browser)                  local machine                     Canvas
─────────────────────                  ─────────────                     ──────
open session ─────────────────────────►
  POST /local-sessions                 │
  { institution_key }                  │
  ◄─ { sessionId, code, expiresAt }    │
show: portable EXE + opaque ticket
                                       │ hidden input: PAT
                                       │ → current-process memory only
                                       ├─ GET /api/v1/courses ──────────►
claim ────────────────────────────────►│  (active + completed)
  POST /local-sessions/claim           │
  { code, canvas_user_id, host_label } │
discovery ◄───────────────────────────┤  course metadata only
  POST /local-sessions/{id}/discovery  │
user selects courses in CourseJesus    │
  POST /local-sessions/{id}/selection  │
selection polled ◄─────────────────────┤
                                       ├─ GET file download ────────────►
                                       │  stream → sha256
upload each file ─────────────────────►│
  POST /local-sessions/{id}/files      │
  (bytes + declared size/sha256)       │
finish ───────────────────────────────►│
  POST /local-sessions/{id}/finish     │
```

## Endpoints

All of them require the user's own authentication (`require_user`): the bridge signs in as the user,
exactly like the web app, and a session's owner must match the caller.

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/integrations/canvas/local-sessions/capability` | whether this deployment offers the bridge (`schemaReady`, `localBridgeEnabled`, `reason`) |
| `POST` | `/api/integrations/canvas/local-sessions` | open a session for a **registered** school; returns the one-time code and its expiry |
| `POST` | `/api/integrations/canvas/local-sessions/claim` | claim the session with the code; single use, one user |
| `POST` | `/api/integrations/canvas/local-sessions/{id}/discovery` | the bridge reports the courses it found |
| `GET` | `/api/integrations/canvas/local-sessions/{id}/courses` | what has been discovered, for the page |
| `POST` | `/api/integrations/canvas/local-sessions/{id}/selection` | the courses the **user** chose, in CourseJesus |
| `GET` | `/api/integrations/canvas/local-sessions/{id}/selection` | the selection, for the bridge to poll |
| `POST` | `/api/integrations/canvas/local-sessions/{id}/files` | one downloaded file, as bytes |
| `POST` | `/api/integrations/canvas/local-sessions/{id}/finish` | end the import and count the outcomes |
| `POST` | `/api/integrations/canvas/local-sessions/{id}/cancel` | stop the import; ingested files stay |

## What the server refuses, and why

| Refusal | Code | Reason |
|---|---|---|
| a code that does not exist, or belongs to someone else | `LOCAL_SESSION_NOT_FOUND` (404) | the same answer for both, so a bridge cannot probe which codes exist |
| a code used twice | `LOCAL_SESSION_ALREADY_CLAIMED` (409) | the `UPDATE … WHERE status='OPEN' AND claimed_at IS NULL` is the arbiter, so two racing bridges cannot both win |
| a code past its expiry | `LOCAL_SESSION_EXPIRED` (410) | 30 minutes, and the row is marked `EXPIRED` when it is refused |
| a school that is not in the registry | `CANVAS_UNKNOWN_INSTITUTION` (400) | an authorisation flow pointed at an arbitrary host would hand the code to whoever owns it |
| a course that was not discovered | `LOCAL_DISCOVERY_UNKNOWN_COURSE` (400) | the bridge cannot invent a course, and the user can only choose from what was found |
| a file for a course the user did not select | `LOCAL_COURSE_NOT_SELECTED` (403) | discovery is not consent |
| bytes that do not match the declared digest | `LOCAL_FILE_HASH_MISMATCH` (409) | a manifest cannot claim content it did not send |
| bytes that do not match the declared size | `LOCAL_FILE_SIZE_MISMATCH` (409) | same |
| a display name that is a path | `LOCAL_FILE_NAME_UNSAFE` (400) | separators, control characters, `.`/`..`, `~`, reserved DOS names |
| a file before a selection or after a finish | `LOCAL_SESSION_WRONG_STATE` (409) | the order is the protocol |

Every one of those is covered by `services/rag-api/tests/test_canvas_local_bridge.py` (29 tests), which
drives the real application: real routes, real database, real `IngestionService`. Two defects were
found by writing it, both of which would have shipped:

* `get_job` on a **private user course** answers `JOB_NOT_FOUND` when the caller does not name the
  owner. The bridge queued and processed a document successfully and then reported the job missing;
  the read now passes `owner_user_id`/`is_admin=False`.
* `REJECTED` was missing from the `canvas_local_files.status` CHECK constraint, so the first file in a
  format outside the upload allow-list (a `.zip`) raised `IntegrityError` → a 500 instead of a typed
  receipt.

## What the import produces

* one **private** course per (user, institution, Canvas course): `course_type='user'`,
  `visibility='private'`, `publication_status='private'`, owner = the signed-in user, never campus,
  official, shared or public;
* documents written through the real `IngestionService`, so the deployment's per-course file quota and
  per-user storage quota apply — no hand-written INSERT, no bypass;
* a file whose format no loader can read is stored (`DOWNLOAD_ONLY`) and never counted as learnable
  material; a file the upload layer refuses outright is `REJECTED` with its reason;
* per-file identity is `(session, canvas course id, canvas file id, content hash)`: the same name with
  a different id is two files, the same id with new bytes is a new version rather than a permanent
  skip, and a retried upload of identical bytes returns the first receipt (`duplicate: true`).

## Scope, and what is deliberately not here

The bridge is a *transport*: the user's machine talks to Canvas with the user's own token, and this
service never calls Canvas on that path. The read-only endpoint allow-list, the origin rules and the
token handling that the OAuth worker enforces (`app/canvas/http_safety.py`, `adapter.py`) therefore
apply where the bridge's own local tool runs — that tool is the owner-verified
`canvas-study-assistant` skill, reused rather than rewritten.

Not included, on purpose:

* no upload, submission, grade, quiz, teacher, admin, masquerade or other-student call, on either
  route;
* no URL query, header, log, analytics event or database column that can carry a Canvas token;
* no "connect any Canvas host" flow: an unregistered school is reported *"等待学校开通 Canvas 连接"*
  and the local routes are offered instead of a broken button.
