# STUDENT_VERIFICATION

## Model

- `cmui_verification` (owner, verified, method grandfathered|code|admin, verified_at,
  boundary_notes) — one row per user.
- `cmui_verification_codes`: 7-digit string codes (leading zeros preserved,
  `CHECK(length(code)=7 AND code NOT GLOB '*[^0-9]*')`), stored ONLY as
  HMAC-SHA256(server_secret, code) digests; never plaintext, never bare hashes.
  `status ∈ issued|redeemed|disabled`; owner set on redemption; audit JSON.
- `cmui_redemption_attempts` — rate-limit + audit trail per attempt.
- `CMUI_VERIFICATION_SECRET` env; required in production (validated); stable dev default.

## Rules

- Redemption (`POST /me/verification/redeem`, rate bucket 5/min): one code → at most one
  account (transactional `UPDATE … WHERE status='issued'`); the redeemer re-submitting
  their own code is idempotent-success; other accounts get the uniform failure;
  disabled codes fail; uniform error messages; no code enumeration (list endpoint is
  admin-only and masked).
- Admin issuance: `POST /admin/verification-codes {count}` (admin ids only) returns
  plaintext codes exactly once; `POST /admin/verification-codes/disable`; audit on
  issue/redeem/disable. Codes never appear in logs, git, or reports.
- Grandfathering: one-time boundary at first boot of this feature
  (`cmui_meta.verification_grandfather_boundary`), snapshot = pre-existing
  `cmui_users` ∪ (integrated) V3 ownership rows via domain op
  `verification.grandfather_candidates`. Re-running never certifies later users;
  client timestamps never trusted.

## Campus gate

- `display_type='campus'` or `requires_student_verification=1` courses: directory
  metadata visible to everyone, but ALL content endpoints (runs, files, comments,
  knowledge tree, assessments, exercises, explanations, pin, share-join) enforce
  server-side verification (admin bypass for operations only). Old/deep links and
  legacy endpoints are covered because the gate sits at the cmui course-access layer
  used by every proxied operation.
- New users default unverified; private courses remain fully usable without verification.

## Production note

Local simulation + tests cover the whole flow. The production user snapshot and the
actual roll-out of the gate require the deployment round (NOT_PERFORMED here).
