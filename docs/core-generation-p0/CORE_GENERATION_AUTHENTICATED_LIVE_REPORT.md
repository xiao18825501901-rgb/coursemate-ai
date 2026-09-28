# Core generation authenticated live report

Status: **DEPLOYED / AUTHENTICATED FLOWS NOT ACCEPTED**

## Current verified production facts

- Web: `https://coursejesus.com/` returns 200 with title `CourseJesus 学习空间`.
- Web build info reports release
  `916b76ce0534e4ce50a589521b0b618850df6956`, production context, and 18
  artifacts.  The Canvas Bridge ZIP returns 200 as `application/zip` with the
  expected 14,106,289-byte length.
- Active API origins used by the current web release are the sslip.io RAG and
  Agent endpoints; both health endpoints return 200.
- `rag.coursejesus.com` and `agent.coursejesus.com` did not establish TLS during
  this run and are not treated as active production endpoints.
- Hangzhou application host: `47.114.34.175`; Singapore Caddy/tunnel host:
  `47.237.179.69`.
- OpenJev service is active on the application host, but its four hard-gate
  qualifications remain UNSET after the recorded 0.50 held-out results.
- RAG, Agent and OpenJev services are active.  The post-deploy readiness monitor
  completed successfully for both APIs, the latest backup and disk headroom.

## Acceptance state

No authenticated live user flow has been executed against the deployed release.
Local fake-provider, real self-hosted OpenJev qualification, authenticated live
generation, and production deployment are reported separately.  This document
must not be changed to PASS until the exact browser flows are read back from
production.

An automated bounded acceptance attempted to use Clerk's supported one-time
test-session path.  The installed protected Clerk Backend API credential returned
HTTP 403 for synthetic-user creation and also for a read-only user-list request.
No identity was created, no paid model call was started, and no real user was
impersonated.  This is an identity-access blocker, not evidence that the teaching
flow failed.

The following cannot currently pass honestly:

- a new campus/private READY “做一题” generated through the unqualified hard gate;
- the private SQL zero-pool five-question Assessment through READY and grading.

Healthy campus teaching and private teaching can still be accepted separately
after deployment with one bounded real DeepSeek run each.

## Deployment facts that are verified

- Backend immutable release: `/srv/coursemate/releases/916b76c`.
- Frontend production deploy: `6abacab3d2f4fb9cbfb7d8e9`.
- Database: Schema 64, integrity `ok`, zero foreign-key violations.
- OpenJev: loopback readiness PASS, approximately 1.45 GB live memory, hard
  definition modes zero.
- Authenticated campus/private normal, Thinking, do-one and Assessment flows:
  **NOT VERIFIED** for this release.
