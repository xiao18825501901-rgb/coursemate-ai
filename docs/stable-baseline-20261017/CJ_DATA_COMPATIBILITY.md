# Data compatibility and protection record

Captured: 2026-10-17 (Asia/Shanghai)  
Candidate branch: `feature/stable-baseline-upgrade-20261017`  
Production application baseline: `deb82cc518b2f48cd11329a7d316e9eadeea30ce`

This record deliberately contains aggregate counts and schema identities only. It does not contain
student text, account identifiers, credentials, cookies, model inputs/outputs or provider tokens.

## Directly observed production authority

The active service opens the existing three SQLite authorities in place:

| Store | Production schema | Aggregate evidence | Status |
|---|---:|---|---|
| RAG/learning | migration 81 | 55 workspaces, 4,733 operations, 7,356 specs, 180 question revisions, 14 assessment sessions, 8 submission revisions, 7 grade snapshots, 5,054 model-call reservations | `DIRECTLY_OBSERVED` |
| UI extension | schema 16 | 237 runs, 254 messages, 37 exercises, 26 answer reveals, 11 step explanations, 100 Pair links | `DIRECTLY_OBSERVED` |
| Agent | migration 3 | zero current task/chat rows in the inspected authority | `DIRECTLY_OBSERVED` |

The counts are not acceptance results; they establish that the current databases contain durable
post-baseline records which must not be replaced by an older database or recomputed.

## Candidate compatibility behavior

The candidate is based on the exact deployed source baseline. Its compatibility behavior is:

- RAG code declares migrations through 69, but readiness checks require the complete prefix through
  69 and accept later additive migrations. Initialisation applies only missing known migrations; it
  has no reverse-migration path and does not delete migrations 70–81.
- UI code declares schema 15 and fails closed for arbitrary future databases. It explicitly accepts
  only the reviewed additive schema-16 shape: the private error-detail column, two immutable teaching
  journals, and their immutability triggers must all be present. It preserves the schema-16 marker.
- Agent code requires migrations 1–2 for readiness and uses additive, idempotent DDL. The production
  migration-3 record is retained; no destructive statement is present in its initialisation path.
- The production services running this exact source combination have already opened schemas 81/16/3
  successfully. That is operational compatibility evidence, but it is not a substitute for the
  isolated-copy startup and write-path rehearsal required before a new release.

## Verified recovery point

The latest inspected persistent backup is:

`/srv/coursemate/backups/coursemate-v2-20261015T193630.750321Z`

Its manifest records all three databases plus both stored-file roots. SHA-256 verification succeeded
for every manifest entry. Each SQLite database reported `integrity_check=ok` and zero foreign-key
violations. The backup is a recovery point, not permission to overwrite newer production data.

## Isolated-copy rehearsal

Status: `PASS`.

Exact read-only copies of the verified backup were transferred into the independent project runtime.
The large RAG database used a compressed stream, avoiding another temporary file on the 94%-full
production disk. The received identities are:

| Store | Bytes | SHA-256 |
|---|---:|---|
| RAG | 703,983,616 | `5c025597cffde51d5ffdbbb420363fdbec23d29ba346f250d14c62d65bb8c67b` |
| UI | 19,152,896 | `597611f4da7ceea1a5c6feeb172c73481b9e118e7f977238ccbe20fd0864d5c6` |
| Agent | 69,632 | `365d3786dfc52b554f71909f5f642ef65fcaef51ee2138564cdc47edf592335b` |

Each SHA-256 exactly matches the persistent backup manifest. Separate startup-rehearsal copies were
then created; the sealed received copies were never opened for candidate initialisation. On the
rehearsal copies:

1. RAG initialisation completed, `is_ready=true`, and maximum migration remained 81;
2. UI initialisation completed and the schema marker remained 16;
3. Agent initialisation completed, `isReady=true`, and maximum migration remained 3;
4. all three post-startup copies returned `integrity_check=ok` and zero foreign-key violations;
5. the sealed received copies were re-hashed afterward and still matched all three manifest hashes.

These checks prove startup/read compatibility and non-destructive initialisation. Representative
student write-path tests remain stage-specific gates for Do One, assessment, RAG and history; this
S0 result does not claim those later business acceptances.

## Release invariants

- Never point an old binary at production for a migration rehearsal.
- Never run a destructive reverse migration or replace the current databases with a September copy.
- Never clear old `RUNNING`, `RESERVED` or `UNKNOWN` records as a release shortcut.
- Preserve immutable question/assessment revisions and historical scoring snapshots exactly.
- Store the pre-release backup identity before any production write, then use an atomic code switch.
- If rollback is required after new user writes, roll code back while retaining the current databases;
  do not restore an older database over newly created data.

## Current conclusion

`COMPATIBILITY = PASS` for source identity, isolated startup, schema preservation, integrity and
foreign-key safety. `RELEASE_DATA_GATE = PASS_FOR_STAGE_S0`. Every later release still needs its own
backup-first migration rehearsal and the affected real business-path tests; this result is not a
blanket approval for future migrations or production writes.
