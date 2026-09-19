# Independent audit evidence matrix

2026-09-20 recovery continuation supersedes the old recovery boundaries below:
Windows bounded first-command restore and controlled PREPARING recovery are locally verified;
native WSL ext47 PASS, DrvFS remains FAILED; sidebar fixed with final13 browser PASS.
Frozen code `dcfd322`; full regression is recorded in RECOVERY_GATE_AND_REMAINING_STATUS.md.
Historical 645/2 and provenance UNKNOWN are preserved, never promoted to live acceptance.

Baseline `9104b5ae5cc767a57d804131b01b925728552cb5`, branch
`fix/codex-dsh-audit-20260919`. Owner confirmed DSH stopped.
Only the D-drive repository was modified. Original DSH reports are historical
claims, not current runtime evidence. This matrix supersedes its initial
all-pending snapshot; earlier RED reports remain intentionally preserved.

“Local verified” below means synthetic DB and external-provider fixtures; it
never means paid model, Clerk production, real messages or production acceptance.
See TEST_REPORT.md for exact run counts, failures and code-state qualifications.

| Req | DSH claim / independent finding | Implementation and independent evidence | Local disposition |
|---|---|---|---|
| R01 Names | Existing course display normalization | Existing migration 025/domain DTO retained; current-change and legacy integration tests | Retained; regression suite |
| R02 Status | Existing generation labels, redundant persisted-status wording | pages.jsx clears successful transient labels; mounted generation/cancellation and browser lanes | Implemented; browser checks |
| R03 Controls | Existing controls lacked keyboard attachment/resize support | Composer/files labels keyboard-enabled; direction-key step move/resize; mobile/divider/focus browser checks | Fixed after actual browser RED |
| R04 Templates | Claimed 14 professional and 3 task templates | Full normalized Word bodies independently compared; 17 source hashes + OTHER required clauses | 18 template regressions; no rewritten body |
| R05 Classification | Integrated samples empty; stale worker overwrites possible | Authorized bounded parsed body/version sampling; persisted claim/revision CAS; newest pending work; manual precedence | Same-name changed-body real V3 + stale-worker unit contracts |
| R06 Normal/Thinking | Existing plan/work pipeline | Original full template provider preserved; isolated HTTP contract counts and browser mode toggle | Offline verified, real model NOT RUN |
| R07 Plan privacy | Historical event/error payloads exposed internals | public_events closed projection on producer/replay; no plan in public history/share/error | Canary HTTP/SSE replay tests; no perfect model guarantee |
| R08 Binding | Integrated arbitrary node accepted; first claim fragile | Authorized real node lookup; durable node_starts; atomic open/get-or-create; conflict checks | node_open/pair_lifecycle integrated regressions |
| R09 Pair history | Recent incomplete lanes could merge; delayed layout replaced current Pair | Explicit pair_id; independent legacy lanes; revision-guarded exact restoration; attachment/exercise state | Backend and real browser reload/held-response race |
| R10 Exercise | Course-global recent binding chosen | Explicit current Pair; authorized node title/evidence; ambiguous missing Pair rejected | exercise_context + browser two-Pair check |
| R11 Hidden answer | Split marker leaked before reveal | Buffer/validate full response before public question; legacy replay sanitization; reveal receipt | All marker splits/malformed responses/API/history/SSE; browser network surfaces |
| R12 Supplied problem | Markdown-only steps insufficient | Persistent exercise/answer/step version; direct normal answer, saved revealed state | problem_versions + strict browser exact run/step |
| R13 Explanation | Pre-reveal access; cached replay/concurrency/restart gaps | Reveal gate; full action hashes; transactional coalescing; scoped follow-up; silent cancel; lease recovery; rich-content windows | action_idempotency, cancellation, recovery, rich-content DOM and real multiwindow browser |
| R14 Send snapshot | Zero integrated files; invalid selected IDs; partial sends | Frozen bytes/indexes/manifest; selected bound pairs; payload hash; same-request caught-failure resume; atomic ready+notices; read-consistent history/knowledge | sharing/share_recovery/snapshot_review; process-killed PREPARING recovery remains operational boundary |
| R15 Join snapshot | Created empty V3 course, no file import | Formal ingestion snapshot service; deterministic course/receipts; own files/versions/chunks; mapped knowledge/history/attachments/answers/classification | Three-file true V3 retrieval/download, sender deletion, outsider isolation, concurrent/quota retry; local standalone regression also fixed |
| R16 Directory/inbox | Two-character minimum, local LIMIT20; tabs did not switch | Opaque projected full directory, pagination/search/privacy/block; protected paginated Clerk client; tab fix; join refresh; notices beyond100 | Directory fake HTTP7, identity tests, browser; actual registered sync NOT RUN |
| R17 Campus gate | Only selected new routes guarded | Central course policy, workspace inheritance, original QA/history read/mutations, refreshed history/events/retrieval/share | Revoked/new user endpoint and browser403 checks; metadata allowed |
| R18 Seven-digit codes/old users | Raw codes persisted; old nonvisitor omitted | HMAC+opaque code IDs/tombstones; explicit complete registered cutoff receipt; retryable protected grandfather | Schema6 migration, concurrency/leading zeros, fake HTTP registered snapshot; real grants NOT RUN |

## Evidence gaps and boundaries

- Final raw backend suite: 645 pass, 2 Windows restore-publication failures.
  The two exact preserved synthetic staging directories were subsequently
  reverified and explicitly resumed successfully; the original failures remain
  recorded, not retrospectively changed to PASS.
- Knowledge snapshot read-transaction fix was made after that full suite started;
  its independent RED-to-GREEN test passed separately. Do not claim the full
  suite uniformly covered a later immutable commit.
- Expanded browser suite:12 pass after UI fixes and synthetic actor isolation;
  no production identity bypass was enabled.
- Historical vector provenance is absent; configured embedding labels alone do
  not prove old index lineage. Production requires an explicit lineage decision.
- No real model, production access/deployment, Clerk sync, real private messages,
  real sharing, eligibility changes or Git push occurred.
