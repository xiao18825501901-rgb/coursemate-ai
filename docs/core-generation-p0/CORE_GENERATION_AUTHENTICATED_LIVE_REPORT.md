# Core generation authenticated live report

Status: **PENDING DEPLOYMENT / NOT ACCEPTED**

## Current verified production facts

- Web: `https://coursejesus.com/` returns 200.
- Active API origins used by the current web release are the sslip.io RAG and
  Agent endpoints; both health endpoints return 200.
- `rag.coursejesus.com` and `agent.coursejesus.com` did not establish TLS during
  this run and are not treated as active production endpoints.
- Hangzhou application host: `47.114.34.175`; Singapore Caddy/tunnel host:
  `47.237.179.69`.
- OpenJev service is active on the application host, but its four hard-gate
  qualifications remain UNSET after the recorded 0.50 held-out results.

## Acceptance state

No authenticated live user flow has yet been executed against the new candidate.
Local fake-provider, real self-hosted OpenJev qualification, authenticated live
generation, and production deployment are reported separately.  This document
must not be changed to PASS until the candidate is deployed and the exact browser
flows are read back from production.

The following cannot currently pass honestly:

- a new campus/private READY “做一题” generated through the unqualified hard gate;
- the private SQL zero-pool five-question Assessment through READY and grading.

Healthy campus teaching and private teaching can still be accepted separately
after deployment with one bounded real DeepSeek run each.
