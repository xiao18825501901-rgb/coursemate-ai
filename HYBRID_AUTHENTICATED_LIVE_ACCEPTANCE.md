# HYBRID_AUTHENTICATED_LIVE_ACCEPTANCE

Status: **NOT EXECUTED THIS ROUND**

This document records exactly which authenticated flows were attempted, which
were not, and why.  It must not be changed to PASS without the flows being read
back from production.

## 1. What blocked it

The acceptance flows in the brief are all "a new question is authored, reviewed,
published and then answered by a real learner":

```text
campus / private “do one question” →  reveal → step explanation → Pair recovery
private SQL course 0/5           →  5 published → submit → per-question grade
another campus objective N=8     →  full pool → submit → grade
```

Every one of them requires a **newly published READY question**.  This round's
held-out qualification shows the only configured reviewer chain cannot yet be
qualified for any of the four cases (`HYBRID_QUALIFICATION_AND_REGRESSION.md`
§3.5), and the local OpenJev candidate has no usable signal.  So a new question
cannot be published, and an authenticated run would exercise the same
fail-closed refusal that the unauthenticated contract tests already cover.

Running the browser flow anyway would produce a page showing a generation
failure.  That is not acceptance evidence, and it is not reported as any.

## 2. What was verified instead, at the layer each claim belongs to

| Claim | Verified? | Evidence |
|---|---|---|
| Production is serving the deployed release | **yes** | `/srv/coursemate/current → /srv/coursemate/releases/916b76c`; `coursemate-rag`, `coursemate-agent`, `coursejesus-openjev` all `active` |
| OpenJev local service is live and ready | **yes** | `GET /ready` → `{"status":"ready","saturated":false}`; 1 418 148 KB RSS |
| The OpenJev adapter path is exercised for real | **yes** | live one-shot probes: empty descriptions → 422, real descriptions → 200, no descriptions → 200 |
| The two DeepSeek reviewer roles are exercised for real | **yes** | two live calls with distinct response ids and verified references |
| The publisher refuses an unqualified review | **yes** | `tests/test_hybrid_publication.py::test_without_a_qualification_the_hybrid_receipt_cannot_accept` and `::test_an_out_of_scope_qualification_cannot_accept`; and the live qualification recorded `DRAFT` with no row written |
| The publisher's refusal is what the learner sees today | **yes (by construction)** | `question_runtime.py` raises `QUESTION_NOT_READY`; `cm_update` projects `QUESTION_ENGINE_FAILED` |
| A real Clerk browser session can complete a new do-one flow | **NO** | cannot be, while no question can be published |
| A real learner was impersonated | **No, and none was** | no synthetic JWT, no `AUTH_TEST_USER_ID`, no copied cookie store, no real account used |

## 3. The Clerk Backend API 403 blocker

The previous round recorded that the installed Clerk Backend API credential
returns HTTP 403 for a synthetic-user create and for a read-only user-list.  That
was **not re-attempted** this round, and deliberately so: the brief says not to
keep hammering the management API, and re-probing it would not have changed the
outcome of anything below.

The correct conclusion is unchanged and worth restating precisely:

* a 403 on the **management** API is not evidence that ordinary Clerk sign-in is
  broken;
* it is a real blocker to *automated* creation of a test identity;
* it is **not** the reason authenticated acceptance was not executed this round.
  The reason is §1: there is nothing publishable to accept.

## 4. Owner action card (one concrete step, no guessing)

When the reviewer chain is qualified, the authenticated acceptance needs exactly
one human action, and only this one:

> Open `https://coursejesus.com/` in the owner's own browser and sign in normally
> through the Clerk page (MFA as usual).  Then open the private *Database System*
> course, start the configured Assessment, and leave the tab open.

Everything else — starting the run, polling preparation status, revealing the
answer, submitting, grading — is driven by the acceptance driver against that
already-authenticated browser session.  No password, cookie, ticket or token is
ever pasted into a report, a log or a chat.

If a second account is needed for the two-user isolation check, it should be
created by normal self-registration, not by the management API.

## 5. Not-run acceptance items

| Item | Status |
|---|---|
| A. OpenJev positive/negative/over-long/non-English/outage cannot decide alone | **partially covered by tests**; the live positive/negative probes ran, the over-long and outage paths are covered by `test_the_local_observation_is_recorded_but_never_decides` |
| B. Two DS roles give independent, traceable receipts; a FAIL/UNCERTAIN or a fake quote cannot release | **covered by tests**, and the live pair produced verified traceable receipts |
| C. A shared mistake / two correct options / SQL NULL and duplicate errors are not outvoted | **covered by tests** for the deterministic side; the reviewer side is exactly what failed the qualification |
| D. Campus and private "do one question" with reveal, step explanation and Pair recovery | **NOT RUN** — nothing publishable |
| E. Private SQL 0/5 → 5 published → submit → per-question grade; another campus objective N=8 | **NOT RUN** — nothing publishable |
| F. Normal and Thinking knowledge teaching, text and image explanations do not regress | **NOT RUN authentically**; source unchanged and the existing regression suite is green |
| G. Another user cannot read the private course, answers, receipts, preparation job or cache | **NOT RUN authentically**; unchanged source, existing isolation tests green |
| H. Concurrent preparation, restart, cross-pane, course switch, cancel, parse failure, UNKNOWN receipt | **partially covered by the existing regression suite**; unchanged source |
| I. The pipeline does not rewrite old grades/exposure/in-progress assessments | **verified by reading production**: no student-facing row was touched this round; the migration rehearsal proves historical row digests are unchanged |

## 6. Honest summary

`AUTHENTICATED_BROWSER_ACCEPTANCE` is **NOT ACHIEVED**, and the reason is not a
browser-tool problem, a Clerk-permission problem or a missing credential.  It is
that the semantic review chain this round built does not yet pass its own
qualification, so no new question can reach a learner.  Reporting anything else
would be reporting a page that says "generation failed" as a restored feature.
