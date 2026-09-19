# CourseMate production release execution — 2026-09-20

Status: **DEPLOYED AND PUBLICLY VERIFIED**  
Application release: `aa3ffc250c2c4584f35dceea1a9ceec61123fdef`  
Branch: `fix/codex-dsh-audit-20260919`  
Final Netlify deploy: `6aaef108d89499d9a5e52722`

This report records the actual release operation. It supersedes the PREPARE-only state in
`ACCESS_READINESS.md` and `RELEASE_APPROVAL_PACKAGE.md`; those files remain historical approval
artifacts. No secret, private course body, plaintext verification code or user contact detail is
recorded here.

## Release evidence

- Exact-code backend regression: **684 passed**, 0 failures/errors/skips; two existing dependency
  deprecation warnings.
- Web: **60 passed**; Agent: **66 passed**; typecheck and production build passed.
- Existing same-source browser suite: **14 passed**; production browser checks below are additional.
- The release fixed the migration rehearsal's legacy-column comparison and explicitly disabled
  provider-native thinking for structured V3 Responses calls.
- Real `qwen3.8-max` Responses canary completed Planner, Teacher and image Problem calls. Actual
  estimate was **USD 0.042544** against a conservative **USD 0.150502** ceiling. The earlier
  500/1,400-token incomplete checkpoints were retained rather than overwritten. Human teaching
  quality review remains distinct from protocol/schema completion.

## Data migration and identity

- Authoritative source: Singapore `47.237.179.69`; destination: Hangzhou `47.114.34.175`.
- Final drained source recovery unit:
  `/home/admin/coursemate-backups/final-aa3ffc2/coursemate-v2-20260919T202006.598907Z`.
- Checksum-verified off-host copy:
  `/srv/coursemate/incoming/coursemate-v2-20260919T202006.598907Z`.
- Active versioned data:
  `/srv/coursemate/data/releases/20260919T202006Z`.
- Final post-validation backup:
  `/srv/coursemate/backups/post-aa3ffc2/coursemate-v2-20260919T204135.898002Z`.
- Recovery unit: RAG, Agent and UI SQLite databases; 67 RAG uploads / 124,236,993 bytes; UI uploads
  and share snapshots. SHA-256, SQLite integrity and foreign-key checks passed.
- RAG Schema **25**, Agent Schema **1**, UI Schema **11**. Migrated counts included 9 courses,
  67 documents, 1,963 chunks, 70 ingestion jobs, 6 UI conversations, 19 UI messages and 10 runs.
- Frozen Clerk qualification snapshot: 7 complete records, cutoff `1789849125466`, snapshot SHA-256
  `9f0eaf2f3304985bf44005e174c60ae8980d9ce24497bb8b4d4d0a46b5705b96`, candidate-set SHA-256
  `4226f58941962690b775da0b96b1f08b4f99f24699af519f6fbc50ccc9f9b5af`. The exact frozen snapshot
  was previewed and applied once; all seven pre-cutoff active accounts were qualified. A full Clerk
  directory sync completed separately.
- Synthetic release-smoke users were deleted from Clerk. Their lifecycle projections were reconciled
  through the normal complete-directory path: 7 active identities and 3 inactive audit tombstones,
  with no local user missing a directory projection.

## Runtime and public cutover

- Active backend link: `/srv/coursemate/current -> /srv/coursemate/releases/aa3ffc2`.
- RAG and Agent run as hardened systemd services on loopback 28000/28001; nginx terminates HTTPS.
- Cloudflare DNS-only A records for `rag.qqttai.com` and `agent.qqttai.com` were transactionally changed
  from `47.237.179.69` to `47.114.34.175`. Cloudflare API, 1.1.1.1 and 8.8.8.8 all observed the new IP.
- The certificate for both backend names is valid through 2026-12-12. Pinned-IP TLS checks passed
  before DNS mutation.
- Netlify production `build-info.json` reports application SHA `aa3ffc2...`, context `production`,
  production API origins and no test identity. Previous known-good production deploy:
  `6aabc979588412babd3147f5`.
- `coursemate-monitor.timer` is enabled and active at five-minute intervals. The first run reported
  healthy RAG, Agent, fresh backup and sufficient disk space.
- The old Singapore RAG and Agent services remain stopped to prevent split-brain writes.

## Production acceptance evidence

- Public site, RAG health, integrated UI-extension health and Agent health all returned HTTP 200.
- Exact-origin CORS passed; unauthenticated protected course access returned HTTP 401.
- Signed-out Chromium: correct login page; no unexpected console/page/request failures. The single
  `/me` 401 is the expected authentication probe.
- Authenticated Chromium using a temporary Clerk user: control panel and all six navigation items
  rendered; the user was deleted after the check.
- CS3481 Chromium flow: real login, real seven-digit verification-code redemption, course add, and
  learning workspace open all passed. The page displayed the knowledge tree strip, Knowledge Learning
  and Problem Solving panes, independent inputs, Thinking control and problem-work action, with no
  unexpected browser failures. No teaching message was sent during this UI smoke.
- Current migrated CS3481 data reports **0 published knowledge-tree nodes**. This report therefore
  proves the dual-pane production surface and access flow, not a populated/audited CS3481 official
  tree. Content population remains separate work.

Evidence screenshots are stored under the ignored release evidence directory:

- `work/release-20260920-aa3ffc2/production-home-final.png`
- `work/release-20260920-aa3ffc2/production-authenticated-dashboard.png`
- `work/release-20260920-aa3ffc2/production-cs3481-dual-pane.png`

## Rollback anchors

1. Application: switch `/srv/coursemate/current` to
   `/srv/coursemate/rollback/current-before-aa3ffc2`, restore the protected environment backup at
   `/etc/coursemate/env-backups/20260920T041900Z`, then restart both services.
2. Frontend: restore Netlify deploy `6aabc979588412babd3147f5`.
3. DNS: `/usr/local/sbin/coursemate-dns-record rollback` verifies the current two-record state and
   transactionally restores both records to `47.237.179.69`.
4. Data rollback is independent and destructive: use the drained source recovery unit only after
   explicitly accepting its RPO. The additive schemas should not be manually removed.

