# Canvas access policy: what the code can do, and what is permitted

This file exists because two different questions were being answered by one word. They are
separated here on purpose, and neither may be used as evidence for the other.

* `PAT_CODE_AND_OWNER_TEST` — **what the code can do**: a task-level transient credential path
  exists, is tested, and works.
* `PAT_PUBLIC_ROLLOUT_ELIGIBILITY` — **what is permitted**: whether that path may be offered to
  students in general. It may not, and nothing in this repository says a school agreed to it.
* `CANVAS_OAUTH_LIVE` — the school's own authorisation flow, which remains **`WAITING_INSTITUTION`**.
* `CANVAS_OWNER_LIVE_TEST` — whether the owner has run a real import against a real school with a
  real token. Reported where it is measured, not assumed here.

Measured at revision `bb9fbfc`, 2026-09-24.

## 1. The four routes to a school, and their status

| Route | Who it is for | Credential handling | Status |
| --- | --- | --- | --- |
| School OAuth (`/connect`) | Every user, the primary path | Stored encrypted outside the database; the user may opt in to keeping it | **Implemented and tested; blocked on the school issuing a Developer Key** (`CANVAS_OAUTH_LIVE = WAITING_INSTITUTION`) |
| Local bridge (`/local-sessions`) | A school that has not issued a Developer Key | The token never leaves the user's machine; the service receives course metadata, file bytes and receipts | Implemented and tested; `CANVAS_LOCAL_BRIDGE_ENABLED` defaults to on because it grants nothing the user does not already have |
| One-off task credential (new) | The **owner's own testing**, on a deployment that enables it | Held in the service process for one task, zeroed on destruction, never written anywhere | Implemented and tested; **off by default**, listed accounts only |
| Local file upload | Everyone, always | No school involved | Unchanged |

## 2. What the new path is, technically

Implemented and evidenced in `CANVAS_TRANSIENT_PAT_DESIGN.md`: a pasted token is held for exactly
one import task, used for the Canvas reads that task needs, and destroyed before any parsing or
indexing starts. It is never persisted — not in a table, not on disk, not in a log — and a restart
loses it, which the product reports rather than hides.

Supporting status codes:

* `CANVAS_TRANSIENT_PAT_IMPLEMENTED` — the store, the schema receipt, the routes and the worker's
  release point exist and are covered by tests (`17 + 32 + 36` tests across the three files, plus
  the 319-test canvas/schema selection that shows no regression).
* `CANVAS_TASK_CREDENTIAL_CLEARED` — the ordering claim, as a property of the control flow: the
  worker fetches in one pass and ingests in another, and releases the credential in between; a test
  asserts the release appears before the first indexing call.
* `CANVAS_IMPORTED_PRIVATE_COURSE_LIFECYCLE` — unchanged by this path: an import still creates a
  private course owned by the student through the real ingestion service, and the job's own states
  and per-file outcomes are unchanged.

## 3. Why it may not be offered to students

Three reasons, in the order that matters:

1. **No institution has been asked.** The school issues Developer Keys and approved integrations;
   accepting a student's personal access token in place of that flow is a decision only the school
   can take. Nothing in this repository is evidence of such a decision.
2. **The school's terms and the token's scope.** A Canvas personal access token carries whatever the
   account can reach, which is broader than "the courses this student chose", and the school's
   acceptable-use rules govern it.
3. **It is strictly worse than the two existing paths for a student.** OAuth gives the school a
   revocable, scoped grant and a record of it; the local bridge keeps the token on the user's own
   machine. A pasted token delivered to the service is the option with the fewest protections, which
   is acceptable for an owner testing their own account and not acceptable as a default for
   everyone.

Consequently: `PAT_PUBLIC_ROLLOUT_ELIGIBILITY = NOT_ELIGIBLE_WITHOUT_INSTITUTION_PERMISSION`.

The code enforces this rather than merely stating it:

* `CANVAS_TASK_CREDENTIAL_ENABLED` defaults to **false**, so a deployment that does nothing offers
  the path to nobody;
* the capability is reported **per account** (`taskCredential.available` in
  `GET /institutions`), so enabling it for the owner does not enable it for others;
* the screen renders nothing at all when the capability is false — not a disabled button, which
  would advertise a path nobody can take;
* the public connect screen keeps its own sentence, that this site does not accept personal access
  tokens, and a build-time check fails the production build if that sentence disappears.

## 4. What would have to be true before this changed

In order, and each one is evidence rather than intention:

1. A school states, in writing, that a personal access token path is acceptable for its students,
   and says for what (which courses, how long, with what review).
2. The scope question is answered: what a token can reach versus what the student chose to import,
   and how the service refuses the difference.
3. Retention and revocation are agreed: how long the service may hold the credential, how a student
   or the school revokes it, and what happens to already-imported material.
4. The status code changes from `NOT_ELIGIBLE_WITHOUT_INSTITUTION_PERMISSION` to a value that names
   the authorisation, with the document that records it linked here.

Until then the answer to "may students use this?" is no, and the default configuration already
enforces it.

## 5. The honest gaps in this document

* **`CANVAS_OAUTH_LIVE` is not verified live.** The flow is implemented and covered by tests
  including a simulated school, and no real school callback has been observed, because no Developer
  Key has been issued. `WAITING_INSTITUTION` means exactly that.
* **The local bridge's real end-to-end run is not verified here.** Its tests cover the routes and
  the refusal rules; whether the separate bridge program behaves as documented on a real machine is
  not something this repository can measure.
* **The owner's live test has not been run at the time of writing.** It needs a replacement token
  supplied through a local hidden prompt; the two tokens pasted into chat must be revoked and were
  never copied into any file. Its result belongs in `CANVAS_CREDENTIAL_LIFECYCLE_EVIDENCE.md` when
  it happens, and until then that file must not claim it.
* **The public policy is a product decision, not a code property.** This document records where the
  code stands; it cannot record a permission that does not exist.
