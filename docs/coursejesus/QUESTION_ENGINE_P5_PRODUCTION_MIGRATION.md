# CourseJesus P5 production snapshot and migration evidence

Date: 2026-09-25
Production application observed: `4ef50642c0b2336e64c384752ea262901a32d81d`
Rehearsed candidate: `4305955f161f5bb247cc3908d88d8481dfdf1a84`
Final local candidate: `a24fac535eda85358965f516964df0c40510e7a0`

The final local SHA differs from the rehearsed candidate only by test-process environment
isolation. Application and migration code are identical. This supports reuse of the production
snapshot rehearsal, but it does not turn the candidate into a deployed release.

## Production facts observed

| Fact | Value |
|---|---|
| Host alias / public IP | `coursemate-prod-new` / `47.114.34.175` |
| Active immutable release | `/srv/coursemate/releases/4ef5064` |
| Services | RAG, Agent and nginx active |
| Provider | Qwen `qwen3.8-max`, Singapore Model Studio compatible endpoint |
| Jev production modes | unset; no TypeSafe credential observed |
| RAG | schema 25; 20 courses; 67 documents; 16 workspaces; integrity ok; FK 0 |
| UI | schema 13; 20 users; 13 exercises; integrity ok; FK 0 |
| Agent | one migration; 0 tasks; integrity ok; FK 0 |
| Public site | `qqttai.com` remains the older CourseMate site; CourseJesus domain was not a usable deployed service |

## Verified recovery unit

Fresh backup:
`/srv/coursemate/backups/coursemate-v2-20260925T064343.776717Z`

It contains the RAG, Agent and UI databases, original uploads, UI/assessment attachments, share
snapshots, checksums, SQLite checks and a strict non-secret release descriptor. Credentials remain
external and are explicitly not archived. Manifest SHA-256 is
`2b3f0f2245c3f200140329cb9bcba2b0d49a154d66d96682431bd778628f4b63`; release descriptor
SHA-256 is `af57a54a587aa05b647186d077a8ab6800d3ff5d261755781e93d07d23dc870c`.

The first backup command selected system Python 3.10 and failed before a backup directory was
created because the project requires Python 3.11+. Services were restored and healthy. The same
frozen scripts were then run with production's managed Python 3.12 and completed.

Restore target:
`/srv/coursemate/rehearsals/p5-20260925T064343Z/restored`

All three restored databases returned `integrity_check=ok` and zero foreign-key violations. This
is a real restored production snapshot, not a synthetic database.

## Schema 25 → 39 rehearsal

The restored RAG copy was migrated through contiguous versions 1–39. Old business-table row counts
and fingerprints remained unchanged; post-migration integrity is ok, foreign-key violations are
zero and the V3 invariant audit is green. Representative nonzero retained data includes 67
documents/versions, 4 problems/solutions, 19 steps, 8 publication review snapshots, 2 releases,
664 publication resources, 70 model-run evidence rows and 140 reservations.

Evidence file SHA-256:
`bb368e5b0df20a5317e11c05ca2abfb9a65bf5f1ef47637082cb585d1cc01067`.

The P5 target is schema 39, which includes the previously required schema-38 Question Engine work
plus migration 039 for practice metering and reconciliation integrity.

## What was not changed

No production schema migration, release symlink switch, model change, Clerk change, DNS change or
frontend deploy occurred. The only production writes were non-serving backup/rehearsal artifacts,
a monitor-readable copy of the verified backup, and the minimum parent-directory mode needed for
the existing `coursemate` monitor user to traverse its configured backup root.

Versioned summary: `docs/coursejesus/evidence/p5/production-rehearsal-summary.json`.
