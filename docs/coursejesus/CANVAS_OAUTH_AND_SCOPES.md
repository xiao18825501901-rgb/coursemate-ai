# CANVAS OAUTH AND SCOPES (task B2/B3)

**State of this document.** Round-44 design pass; **the flow itself was implemented in round 47**
in `services/rag-api/app/canvas/oauth.py` and is covered by 22 tests (state replay/expiry/forgery,
denial, exact callback, error classification, identity binding and account replacement, concurrent
refresh, revocation, redaction). The protocol facts below were verified against Instructure's own
documentation (markdown endpoints under `https://developerdocs.instructure.com/`), and the design
decisions follow from them. **No school Developer Key exists yet, no authorisation has been
performed, and the HTTP routes do not exist yet** — so the Canvas status stays `NOT_CONFIGURED`
and will not be reported as connected.

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

## 9. Honest limits

* Everything in §2 is documentation-verified, not exercised against a live Canvas instance; no
  authorisation code has ever been exchanged here.
* The scope identifiers in §3 are the expected `url:GET|<path>` forms and are marked as needing
  confirmation, because the authoritative list is account-specific
  (`GET /api/v1/accounts/:account_id/scopes`) and only a school administrator can read it.
* Canvas's scope listing endpoint is documented as BETA, so the school's own console remains the
  final authority on what it will grant.
* Nothing here changes the Canvas status: it remains `NOT_CONFIGURED` until a school key exists and
  a real student completes a real authorisation.
