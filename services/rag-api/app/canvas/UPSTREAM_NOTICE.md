# Upstream notice and adaptation notes

`app/canvas/` is adapted from the read-only parts of **`hairoom/canvas-study-assistant-skill`**,
reused under its MIT licence.

## Attribution

```text
MIT License

Copyright (c) 2026 Hairong Zheng

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

The upstream repository ships `LICENSE` and no separate `NOTICE` file; this file is the notice
this repository adds, and it records the exact baseline below.

## Baseline

| Fact | Value |
|---|---|
| Repository | `https://github.com/hairoom/canvas-study-assistant-skill` |
| Commit | `f05ffae8e98d3d6860695abe11c59c52718dd277` (2026-09-20) |
| Local modification at baseline | `canvas_study/runtime.py`, 7 added / 1 removed line (see below) |
| Licence | MIT, as reproduced above |

The local modification is **part of the baseline**, not an optional extra: it is what makes the
`active` **and** `completed` student-course requirement satisfiable. It widens
`validate(base, token)` to page `enrollment_state=completed` when the active page yields no
student enrollment, and it re-applies the student-type filter (`type == "student"` or
`role == "StudentEnrollment"`) to that page rather than trusting the parameter. If the upstream
checkout is ever updated, that behaviour must be re-applied deliberately — a plain `git pull`
would drop it.

## What was reused

* The read-only discovery shape: courses for the authorised user, then per-course file metadata,
  with `Link`-header pagination followed to the end.
* The error-classification idea (`status` → category) and the distinction between rate limiting
  and a hard refusal.
* The same-origin check on pagination links.
* Dropping the `Authorization` header when a request leaves the Canvas host (upstream's
  `SafeRedirectHandler`), generalised here into per-hop validation.

## What was deliberately not reused

The upstream runtime is a single-user desktop tool. It uses an OS-level `config.json`, a
module-level client singleton, an on-disk cache and session file under the user's app directory,
and OS keychain / Windows Credential Manager storage. It also exposes a broad MCP tool surface and
an application layer with write operations.

In a multi-user service each of those is a defect: shared "current Canvas" state lets one user's
request affect another, a shared cache leaks across users, per-user OS credentials cannot exist on
a server, and a broad tool surface or write path is exactly what the product forbids. This module
therefore exposes a fixed allow-list of read endpoints, requires injected connection context, keeps
no cache, and cannot issue anything but `GET` for learning APIs.

## Modifications relative to upstream

| Change | Reason |
|---|---|
| `httpx` clients with injected context instead of `urllib` + module globals | no global state; testable transport (a mock transport replaces the network in tests) |
| Explicit endpoint allow-list (`ALLOWED_ENDPOINTS` + course-scoped prefix) | the upstream accepts caller-supplied paths; a web service must not become a Canvas proxy |
| Single request path that refuses every non-`GET` verb | keeps "read-only" a property of the code, not of the callers |
| `enrollment_state` and `workflow_state` recorded separately | a completed course is readable history, not a failed lookup |
| Per-hop download validation + a token-free download client | a signed URL redirects to a CDN; the Canvas token must not follow it |
| No retries; `Retry-After` surfaced on the error | retry/backoff belongs to the job layer, and a `403` must never be retried |
| Streaming download with a byte limit and SHA-256 | large files must not be buffered in memory, and the local copy needs identity |
