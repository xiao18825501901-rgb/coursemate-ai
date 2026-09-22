# CANVAS SKILL ADAPTATION (task B1)

**State of this document.** Round-44 design pass over the real upstream checkout; **updated in round
46 when the adapter was actually written**. §4's shape is now implemented in
`services/rag-api/app/canvas/` (`registry.py`, `http_safety.py`, `adapter.py`, `UPSTREAM_NOTICE.md`)
with 31 tests and an 8-mutation proof. What the adapter does **not** yet have is stated in §7:
no OAuth flow, no job, no UI, no live Canvas call.

Task B1 requires that the production site *actually reuses* the upstream skill rather than merely
installing it, and equally that the desktop single-user runtime is not turned into a multi-tenant
service by sharing its global state. Both halves are decided here from the measured code, not from
the README's description of it.

## 1. Baseline (measured)

| Fact | Value |
|---|---|
| Local checkout | `D:\Hp\Documents\canvas-study-assistant-skill` |
| Commit | `f05ffae8e98d3d6860695abe11c59c52718dd277` (2026-09-20, "Revise README for clarity and feature description") |
| Working tree | **dirty by design**: `canvas_study/runtime.py` has a local modification that must be preserved |
| Licence | MIT, `Copyright (c) 2026 Hairong Zheng` — retained with attribution; `NOTICE` file is absent upstream |
| Python files | 16 (`canvas_study/` 8, `mcp_server/` 1, `scripts/` 2, `tests/` 5) |
| Upstream tests | `tests/test_application.py`, `test_cli.py`, `test_index_and_registry.py`, `test_resource_discovery.py`, `test_setup_mcp.py` |

The local patch is the active/completed student-enrollment adaptation and it is exactly what task
B requires, so the adaptation baseline is **`f05ffae8` + this patch**:

```diff
--- a/canvas_study/runtime.py
+++ b/canvas_study/runtime.py
@@ -259,7 +259,13 @@ def validate(base: str, token: str):
     courses = api.pages("/api/v1/courses", [("enrollment_state", "active"), ...])
     students = [c for c in courses if any(e.get("type") == "student" or
                 e.get("role") == "StudentEnrollment" for e in c.get("enrollments", []))]
-    if not students: raise RuntimeError("No active student enrollment found; this skill supports students only")
+    if not students:
+        past = api.pages("/api/v1/courses", [("enrollment_state", "completed"), ...])
+        students = [c for c in past if any(...)]           # same student-type check
+    if not students: raise RuntimeError("No student enrollment found (active or past); ...")
     return profile, students
```

Two things it gets right that the production adapter must keep: it widens only the *enrollment
state*, and it re-applies the student-type filter to the `completed` page instead of trusting the
parameter. It is also the reason the client must not simply be "the upstream CLI".

## 2. Reuse (the read-only core)

| Upstream element | Why it is reusable | Production rule |
|---|---|---|
| `Canvas.pages(path, fields, limit=2000)` + `next_url(link, base)` | real Link-header pagination with a same-base check on `rel=next` | keep the same-origin check, and add the allowed-endpoint check the adapter owns |
| `Canvas.get/request` (GET only in practice) | thin, explicit HTTP layer with `Authorization` in the header | never allowed to send a request other than `GET` for learning APIs |
| `CanvasAPIError(status, category, detail)` | typed error categories instead of bare exceptions | map to the job's per-file status (`FORBIDDEN`, `NOT_FOUND`, `RATE_LIMIT`, ...) |
| `SafeRedirectHandler` | drops `Authorization` when a redirect crosses hosts | necessary but **not sufficient**: the adapter still resolves and validates every redirect target (§D of the pack) |
| `validate(base, token)` (patched) | the active **and** completed student-course discovery | reuse, and additionally record `enrollment_state` separately from `course.workflow_state` |
| `resolve(items, query, kind)`, `clean_html`, `CanvasLinkParser` | matching/parsing helpers already exercised by upstream tests | reuse where they apply to file metadata |
| Upstream tests | they pin the HTTP/pagination/registry behaviour | port the ones that cover reused code, with the attribution note |

## 3. Do not reuse (the desktop single-user surface)

Every item below assumes one machine, one active Canvas instance and one human — precisely what a
multi-user site must not have. The production adapter must not import them:

| Upstream element | What it does | Why it cannot be used server-side |
|---|---|---|
| `app_dir()`, `config_path()`, `config()`, `client()` | a module-level `config.json` and a lazily built singleton client | one shared "current Canvas" would let two users' requests interfere |
| `cache_dir()`, `session_path()`, `cached(cfg, category, key, producer)` | on-disk cache and a session file next to the OS app directory | cache must be per connection and per scope, never global; nothing may write session state to a shared path |
| `vault_set/get/delete`, `save_token`, `token_for`, `keyring`, `windows_credential_api`, `mac_vault_*`, `windows_vault_*` | OS keychain / Windows Credential Manager storage | the Owner's personal store must stay untouched, and users' tokens must never be created as per-user OS credentials on the server |
| `output()` | prints JSON to stdout | server code returns values; printing is a CLI concern |
| `mcp_server/server.py` | exposes the skill's MCP tool surface | the pack forbids exposing the whole tool surface; the site exposes exactly one read-only import flow |
| `application.py` / `sync.py` / `index.py` application-layer functions | the local app, including capabilities the pack forbids (assignment/upload paths) | production must not inherit a write path at all |

`application.py` is 28 KB and contains the local workflow; the reusable *mechanics* are in
`runtime.py` (36 KB). The adaptation is therefore a **fork of the HTTP/pagination/error layer with
injected context**, not a wrapper around the CLI, which matches the pack's instruction to make a
minimal fork/refactor rather than to reuse a global-state function.

## 4. Adapter shape

```text
CanvasReadAdapter(
    connection_id,          # opaque; resolves server-side to the registry entry
    normalized_origin,      # one of the registered institutions, HTTPS only
    token_provider,         # callable returning a short-lived token; never a global/env token
)
  .profile()                       -> verified identity of the Canvas account
  .student_courses(states)         -> active/completed courses with a real student enrollment
  .course(course_id)               -> metadata for a course in that set
  .files(course_id, page_cursor)   -> paged file metadata (Link rel=next honoured)
  .file(file_id)                   -> metadata, then a short-lived signed download URL
  .download(url, sink, limits)     -> separate client, no Canvas Authorization header
```

Rules the adapter owns (not inherited from upstream):

* **No global state**: no `CANVAS_ASSISTANT_HOME`, no `config.json`, no shared session file, no
  module-level singleton. Two concurrent users must be unable to affect each other, which is a
  testable property (`tests` will assert that two adapters with different connections never share
  a cache entry or a credential).
* **Origin discipline**: standard HTTPS only, no userinfo, no unusual port, no control characters;
  the requested institution must exist in the registry, and a client cannot pass another
  institution's `base_url` to reuse its secret.
* **GET-only learning API**: token exchange/refresh and user-initiated revocation are the only
  non-GET operations, and they live in a separate OAuth module, not in the adapter.
* **Download discipline**: signed URLs are fetched by a second client with no Canvas
  `Authorization`; every redirect target and DNS resolution is validated as public, HTTPS and
  within the allowed hosts; no HTTPS downgrade; size/type/time limits applied before writing.
* **Nothing reaches the model**: tokens, signed URLs and raw file bytes are not part of any prompt;
  the model sees only the ingested course material the user chose.

## 5. Open items before the adapter is written

1. Confirm the exact read-only scope strings against the current Canvas developer documentation
   (the pack requires the application letter to state them accurately; the draft in
   `CANVAS_ADMIN_OAUTH_REQUEST.md` lists endpoints, not scope names).
2. Decide the minimal fork location inside this repository (probable: `services/rag-api/app/canvas/`
   with the upstream LICENSE text reproduced beside the adapted file, plus a short
   `ADAPTATION_NOTES.md` naming the upstream commit and the delta).
3. Port the upstream tests that cover the reused layer, so a later upstream change can be diffed
   against a known-good baseline.

## 6. Honest limits

* §1–§3 were read from the real code; §4's adapter now exists (§7), but **no Canvas API call has
  been made from the production path** and no institution key exists. `CANVAS_SKILL_REUSE` is
  therefore "implemented and tested against a mock transport", not "verified against a school".
* The upstream checkout is dirty (the owner's patch). Any import of upstream code must pin the
  baseline commit *and* record the patch, or a future `git pull` would silently drop the
  active/completed behaviour the whole feature depends on.
* The upstream `SECURITY.md` and README describe a local, single-user tool; their existing
  hardening (for example the cross-host redirect header stripping) is a starting point, not a
  multi-tenant security design, and this document does not treat it as one.

## 7. What was built in round 46

| File | Contents |
|---|---|
| `app/canvas/registry.py` | `InstitutionConnectionRegistry` with the two CityU entries; per-institution callback, credential *references* (never secrets), and availability derived from whether the key pair actually exists (`NOT_CONFIGURED` otherwise) |
| `app/canvas/http_safety.py` | origin normalisation (HTTPS only, no userinfo, no odd port, no control characters), **exact-pattern** endpoint allow-listing, public-address classification and DNS resolution checks, and per-hop download-target validation |
| `app/canvas/adapter.py` | `CanvasReadAdapter(connection_id, origin, token_provider)` — profile, student courses across `active`+`completed`, course files with `Link` pagination, and streaming downloads through a token-free client |
| `app/canvas/UPSTREAM_NOTICE.md` | MIT text, baseline commit + the owner's patch, reuse list, do-not-reuse list, and the modification table |
| `tests/test_canvas_read_adapter.py` | **31 tests**, including the negative cases: non-`GET` verbs, non-allow-listed paths, absolute URLs on another host, cross-origin pagination links, private/metadata download targets, plain-HTTP and odd-port downloads, redirect chains, byte limits, token-only-in-header, and two adapters not sharing state |

**Two real defects were found by these tests, not by review:**

1. **The endpoint allow-list was a prefix**, so `/api/v1/courses/:id/assignments`,
   `/submissions` and anything else under a course were reachable — exactly the "generic path"
   the pack forbids. It is now a list of exact patterns per endpoint.
2. **`httpx` drops a URL's existing query string when `params` is passed**, even an empty list.
   The adapter therefore re-fetched page 1 forever on a followed next-link: with a real Canvas
   that is an import that never progresses. It now passes `params` only when non-empty, and the
   pagination test asserts the actual request URLs.

A third lesson came from the mutation harness itself: removing the pagination bound outright made
a test loop forever and left the module mutated on disk after the run was killed. The harness now
runs each mutation under a timeout, and the bounds test uses a *finite* 50-page chain so that a
missing bound fails an assertion instead of hanging.

Guards are mutation-proved, not asserted: **8 of 8** mutations were caught (GET-only guard,
pattern allow-list, origin check, private-address check, token-in-query, pagination bound,
cross-origin next-link, download host allow-list), with the module restored byte-for-byte
(`work/current-change/mutation-check-canvas.py`).
