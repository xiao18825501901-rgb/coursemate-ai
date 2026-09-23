# CANVAS OAUTH AND SCOPES (task B2/B3)

**State of this document.** Round-44 design pass; the flow was implemented in round 47
(`services/rag-api/app/canvas/oauth.py`, 22 tests: state replay/expiry/forgery, denial, exact
callback, error classification, identity binding and account replacement, concurrent refresh,
revocation, redaction) and the **HTTP routes plus the encrypted credential store were implemented
in round 69** (`app/api/canvas.py`, `app/canvas/credentials.py`; 39 route tests and 13 credential
tests, with 6 of 6 route/credential guards proven by mutation). The protocol facts below were
verified against Instructure's own documentation (markdown endpoints under
`https://developerdocs.instructure.com/`), and the design decisions follow from them.
**No school Developer Key exists yet and no authorisation has ever been performed against a real
school** — so the Canvas status stays `NOT_CONFIGURED` and nothing here should be read as saying a
school is connected. See §9 for what the routes now do and what they still cannot do.

## 1. Why OAuth and not a token box

The skill the owner ran locally uses a personally generated access token. That is valid for one
person's local tool and invalid for a multi-user site: Canvas's own OAuth documentation describes
the web application flow for applications acting for a user, and developer keys are issued per
institution. The pack's requirement follows from this, and this project adopts it as fixed:

* the public site gets **no PAT input field** and no "paste your token" path;
* encrypting a collected PAT does not make it an acceptable substitute;
* the personal-token instructions stay in the owner's local-tool help only, never as the
  multi-user authorisation method.

## 2. Verified protocol facts

| Fact | Value | Source |
|---|---|---|
| Authorisation endpoint | `GET https://<canvas-install-url>/login/oauth2/auth?client_id=…&response_type=code&state=…&redirect_uri=…` | OAuth file |
| `response_type` | only `code` is currently supported | OAuth file |
| Callback | the `redirect_uri` receives `?code=…&state=…`; the `state` is returned so the app can tie response to request | OAuth file |
| Denied authorisation | `?error=access_denied&error_description=…&state=…` — a normal, recoverable outcome | OAuth file |
| Token exchange / refresh | `POST login/oauth2/token`, with `grant_type` (`authorization_code` for the exchange, `refresh_token` for renewal), plus `client_id`, `client_secret`, `redirect_uri`, and `code` for the exchange | OAuth endpoints |
| Token response | `access_token`, `refresh_token`, `expires_in` (**3600 seconds** in the documented example), Bearer type | OAuth endpoints |
| Revocation / logout | `DELETE login/oauth2/token` | OAuth endpoints |
| Using the token | `Authorization: Bearer <token>` header | OAuth file |
| Scope identifier format | `url:<VERB>\|<path>`, e.g. `url:GET\|/api/v1/courses` | API Token Scopes |
| Enumerating scopes | `GET /api/v1/accounts/:account_id/scopes` — "a list of scopes that can be applied to developer keys and access tokens" (documented as BETA) | API Token Scopes |
| Key ownership | developer keys are scoped to the institution that issues them | OAuth file |
| PKCE | **not shown** in the documented parameters — no `code_challenge`/`code_verifier` | OAuth file/endpoints |

Two consequences taken directly from the table:

1. **`expires_in` of one hour is the design driver.** A refresh path with a per-connection lock is
   required from the start, because a multi-hour import will outlive a single access token.
2. **PKCE is not invented.** The pack says to use PKCE correctly where the provider supports it and
   otherwise not to add self-made fields; Canvas's documented flow uses `state` + `client_secret`,
   so that is what will be implemented.

## 3. Scope strings: how they will be fixed, not guessed

Because the scope list is account-specific and the endpoint that lists it is
`GET /api/v1/accounts/:account_id/scopes`, the application letter lists the **endpoint paths** the
app needs and asks the school to confirm the matching scope identifiers. The scope identifier for
each read endpoint is of the verified form `url:GET|<path>`, so the request will name them
explicitly rather than describing them loosely:

| Purpose | Endpoint | Expected scope identifier (to be confirmed by the school/admin console) |
|---|---|---|
| Confirm the connected identity | `GET /api/v1/users/self/profile` | `url:GET\|/api/v1/users/self/profile` |
| Discover student courses, active and completed | `GET /api/v1/courses` | `url:GET\|/api/v1/courses` |
| Enrollment detail when needed | `GET /api/v1/users/self/enrollments` | `url:GET\|/api/v1/users/self/enrollments` |
| File metadata for a chosen course | `GET /api/v1/courses/:course_id/files` | `url:GET\|/api/v1/courses/:course_id/files` |
| One file's metadata | `GET /api/v1/courses/:course_id/files/:id` | `url:GET\|/api/v1/courses/:course_id/files/:id` |
| Fallback file lookup (still checked against the chosen course) | `GET /api/v1/files/:id` | `url:GET\|/api/v1/files/:id` |
| Folder relationships (only if needed) | `GET /api/v1/courses/:course_id/folders`, `GET /api/v1/folders/:id/files` | as listed by the school |
| Module→file relationships (optional) | `GET /api/v1/courses/:course_id/modules`, `…/modules/:module_id/items` | as listed by the school |

The **not requested** list is part of the same document and is a design constraint, not a
formality: no uploads, no assignment submissions, no grades, no other students' data, no messages,
no quiz answers, no account administration, no SIS, no masquerading, no teacher/admin scope. The
application accepts a narrower scope set and reports what is missing rather than working around it.

## 4. Institution connections

`InstitutionConnectionRegistry`, seeded with the two institutions the owner named:

| Origin | Label | Key |
|---|---|---|
| `https://canvas.cityu.edu.hk` | CityU | its own client id/secret reference and redirect URI |
| `https://cityu-dg.instructure.com` | CityU(DG) | its own client id/secret reference and redirect URI |

Because keys are institution-scoped, the two entries never share a secret, and a client cannot
supply a different `base_url` to make one institution's secret serve another. Per entry the
registry records: origin, label, client id, secret *reference* (never the secret itself), redirect
URI, granted scopes, availability state (`NOT_CONFIGURED` / `AVAILABLE`), and the download-origin
rules.

Callback to freeze once the deployed route is confirmed:

```text
https://rag.coursejesus.com/api/integrations/canvas/oauth/callback
```

## 5. Flow, state and identity binding

```text
signed-in CourseJesus user
  → choose institution
  → server creates a one-time state, short TTL, bound to (CourseJesus subject, institution, nonce)
  → 302 to the school's /login/oauth2/auth with client_id + response_type=code + state + redirect_uri
  → user authorises on the school's own page (their consent, not the owner's)
  → fixed backend callback receives ?code&state (or ?error&state)
  → state is looked up, validated and consumed in every case, success or denial
  → POST login/oauth2/token (authorization_code) → access/refresh token + expires_in
  → GET /users/self/profile and the student-course pages
  → store the connection, 303 back to the import wizard
```

Rules that the implementation must hold:

* `redirect_uri` is exactly the registered value; a client-supplied return URL is never used.
* The `state` carries no token and no readable personal data; it is consumed on both success and
  failure, so a replayed or expired state fails loudly.
* A connection is bound to **(CourseJesus subject, canonical Canvas origin, Canvas user id)**.
  Display name and e-mail are display-only and never merge identities across instances.
* One user may hold both institutions' connections. Attaching a *different* Canvas account to an
  existing connection requires showing the detected identity and an explicit confirmation, so one
  person's courses are never silently reassigned to another.

## 6. Credential lifecycle

| Aspect | Decision |
|---|---|
| Storage | authenticated encryption with a key id, in the existing secret mechanism; the key lives separately from the database |
| What the job holds | only `connection_id` — never a token |
| What never sees a token | the model, any front-end GET, logs, analytics/session replay, error reports, Git |
| Refresh | on `expires_in` expiry, with a **per-connection lock** so two workers cannot refresh concurrently and overwrite each other |
| Default retention | this import only: the credential is cleared once the job and its explicit retry window end |
| Optional retention | the user may explicitly opt in to saving the connection for manual incremental updates |
| Disconnect | immediately blocks new jobs and revokes via the documented `DELETE login/oauth2/token`; it never revokes other applications or all of a user's tokens |
| Imported material | stays after disconnect; deleting it is a separate, explicit action |

## 7. Read-only enforcement (B3)

* The learning API surface is **GET only**. The only non-GET calls in the entire feature are the
  two OAuth token operations (`POST` exchange/refresh, `DELETE` revoke) and they live in a module
  the adapter cannot reach.
* No generic `GET /read_api?path=…` proxy, no dynamic endpoint discovery, and no model-facing tool
  that can call Canvas. The endpoints the app may call are a fixed allow-list, checked in code.
* Origin rules: standard HTTPS only; reject userinfo, unusual ports and control characters; the
  origin must be a registered institution. Every redirect target and DNS resolution is checked to
  be public (no loopback, RFC1918, link-local, metadata addresses or IPv6 equivalents) so a
  student-supplied URL cannot be used to probe the cloud's internal network.
* Pagination follows the documented `Link rel=next` but validates that the next URL stays on the
  same institution origin and inside the allowed endpoint set, and records a resumable cursor.
* Downloads use a **separate client without the Canvas `Authorization` header**, validate each hop,
  refuse HTTPS downgrade, and apply size/type/time limits. Signed URLs never enter manifests,
  ordinary logs or public front-end links.
* `403`/`404`/empty/unsupported/expired/rate-limited/network outcomes are recorded distinctly; a
  `403` is never retried in the hope it becomes a `200`, and a blocked course is never worked
  around.

## 8. What happens while the school has not issued a key

* The wizard shows the real state — "学校连接尚未开通" — with the local-upload fallback, and the
  public UI has no PAT input.
* The application letter (`docs/coursejesus/CANVAS_ADMIN_REQUEST.md`) is ready to send; the owner
  supplies the real contact details and the school supplies the client secret through a protected
  channel.
* Mock-OAuth tests exercise the full state machine (valid state, replayed state, expired state,
  denied authorisation, wrong institution), so the flow is complete and testable before any real
  key exists. Those tests are explicitly **not** evidence that OAuth works with a school.

## 9. The routes, and how a token is stored (round 69)

`services/rag-api/app/api/canvas.py` mounts nine routes under `/api/integrations/canvas`:

| Route | What it does | What it refuses |
|---|---|---|
| `GET /institutions` | Per school: label, origin, `connectable`, and a reason when it is not (`NO_DEVELOPER_KEY`, `NO_CREDENTIAL_KEY`, `SCHEMA_NOT_READY`) | Nothing: it is the route the "school not open yet" state is built from |
| `GET /connections` | The caller's own connections, as public fields only | Any token or key field, by construction |
| `GET /connect?institution=<key>` | 303 to the school's `login/oauth2/auth` URL with the registered `redirect_uri` | An unregistered key; a caller-supplied `base_url` (there is no such parameter) |
| `GET /oauth/callback` | Validates the one-time state, exchanges the code, reads the school's identity, stores the credential, 303 back to a **fixed** path | A forged/expired/replayed state (before any outbound call); an account that would replace an existing connection without confirmation |
| `GET /courses` | The student's own active/completed courses for the selection screen | Another user's connection (reported as absent) |
| `POST /imports` | Freezes the selection into a queued job; the same selection returns the same job | Empty or non-numeric course ids; another user's connection |
| `GET /imports/{id}` | Job status, per-file counts, target course | Another user's job (reported as absent, not forbidden) |
| `POST /imports/{id}/cancel` | Cancels at the next checkpoint; imported material is untouched | A job that is already terminal (reports `cancelled: false`) |
| `DELETE /connections/{id}` | Revokes at the school (best effort) and **always** forgets the local credential | A connection that is not the caller's |

How the token is kept, which is the part the pack is strictest about:

* AES-256-GCM with a random nonce per write and associated data binding the ciphertext to its
  version, key id and connection id; the key comes from `CANVAS_CREDENTIAL_KEY` (32 bytes, base64)
  and lives in no database, no repository and no log. Each record carries a `key_id` (a digest of
  the key) so a rotation is visible rather than silent.
* Files are written under `CANVAS_CREDENTIAL_DIR` (default `data/canvas-credentials`), one per
  connection, named after a digest of the connection id, with a temporary file and an atomic
  replace, `0600`/`0700` where the platform honours permission bits.
* **With no key configured the store does not exist**, and the routes report `NO_CREDENTIAL_KEY`:
  there is no plaintext path and no "store it unencrypted for now" branch.
* The import job stores a `connection_id` only — the migration has no token column at all — so a
  database dump cannot contain a credential, and a restored database alone cannot reach a school.

## 10. The wizard, and the state a real user sees today (round 70)

The two entry points the pack names now exist in the shell
(`apps/web/src/ui/App.jsx`), and both are real `<button>` elements with an underline, reachable by
Tab and activated with Enter:

| Entry point | Where | Element |
|---|---|---|
| Dashboard | the last row of the dashed create card (`控制面板`) | `.add-course-canvas-row` → "从 Canvas 导入" |
| All Courses | the create area at the top of `所有课程` (`course-banner`) | `.canvas-import-link-banner` → "从 Canvas 导入" |

Both open the same wizard (`apps/web/src/ui/CanvasImport.jsx`), which is driven entirely by the
server's own answers through `apps/web/src/ui/canvasImport.js`:

* `GET /institutions` decides the headline. With no Developer Key — the state this deployment is
  actually in — the screen reads **"学校连接尚未开通"**, lists each school with the server's reason,
  and offers **上传本地资料**, which opens the existing create-course form. It never shows a connect
  button that would fail on click, and it has **no credential field of any kind**: the only way to a
  school is that school's own authorisation page, opened as a full-page navigation to
  `/api/integrations/canvas/connect?institution=<key>`.
* When a school *is* connectable, the wizard connects, lists the student's own readable courses for
  selection, posts the frozen selection, and then reports the job the server owns — including
  `COMPLETED_WITH_WARNINGS` (with the reason: pictures and scans are stored but do not count as
  learnable material) and `NEEDS_REAUTH` (reconnect and the unfinished files continue). It never
  claims an import is done on its own authority, and saving the connection is an explicit checkbox.
* The callback lands on the path in `CANVAS_RETURN_PATH` (default `/ui-extension/#/courses`, the
  deployed shell's real URL) with `?canvas=connected|denied|failed` appended **before** the
  fragment, because the shell is hash-routed.

Verified in real Chrome: two new journeys in `tests/e2e/ui-refresh.spec.ts` (21/21 pass) — one
walks both entry points by keyboard and checks the not-open state, the fallback and the absence of
any credential input; the other checks the screen at 390px and in the dark theme. Nine unit tests
pin the client (URLs, methods, the token only in a header, the server's error code surfacing).

Finding while building it: the shell's forms had **no programmatically associated labels**
(`htmlFor` appeared nowhere in `src/ui`). The create-course form — the one the fallback opens — now
associates its four fields; the rest of the shell still needs the same treatment, which is recorded
here rather than quietly half-fixed.

## 11. Honest limits

* Everything in §2 is documentation-verified, not exercised against a live Canvas instance; no
  authorisation code has ever been exchanged here, and the route tests drive a simulated school.
* The scope identifiers in §3 are the expected `url:GET|<path>` forms and are marked as needing
  confirmation, because the authoritative list is account-specific
  (`GET /api/v1/accounts/:account_id/scopes`) and only a school administrator can read it.
* Canvas's scope listing endpoint is documented as BETA, so the school's own console remains the
  final authority on what it will grant.
* **The state and credential stores are per process.** `create_app` wires one shared pair for the
  application, but a multi-worker deployment needs a shared state store before the flow is enabled
  for real users, or a callback can land on a worker that did not issue the state. This is stated
  in the router's own docstring rather than left to be discovered.
* The canvas tables come from migration 031, which is applied with the V3 schema. A deployment
  without the private-course model therefore has no canvas tables, and the routes report
  `SCHEMA_NOT_READY` instead of failing with a missing-table error — the capability is genuinely
  absent there, since the import writes a private course.
* The connect/select/progress steps of the wizard are **not** exercised in a browser, because no
  school is connectable on this deployment; they are covered by the route tests and by the client's
  unit tests, and by the simulated-school suite. A journey that pretended otherwise would be
  claiming an authorisation that never happened.
* Nothing here changes the Canvas status: it remains `NOT_CONFIGURED` until a school key exists and
  a real student completes a real authorisation.
