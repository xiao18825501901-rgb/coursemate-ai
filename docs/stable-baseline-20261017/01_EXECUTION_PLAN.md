# Stable-baseline execution plan

## Slice 0 — current-state evidence

- [x] Validate the Owner package and its five source-report hashes.
- [x] Create an independent worktree from the actual production-correlated source SHA.
- [x] Confirm current Netlify deploy, backend service release directories, health, disks, locks, and
  database schema versions without changing production.
- [ ] Prove byte-level identity for selected deployed runtime files.
- [ ] Record representative current student-path timing without issuing an unapproved paid request.
- [ ] Finish the seven-path dependency and provider-role maps.
- [ ] Freeze `CJ_BASELINE_TRACE.json` and the compatibility report.

Exit gate: every target path has a source entry point, runtime owner, database authority, model role,
known blocking work, and measurable baseline or an explicit evidence gap.

## Slice 1 — safe streaming

Implement and test one public-output stream contract for knowledge learning first, then reuse that
contract for problem response. Only student-visible content may stream. Planning, provider-native
reasoning, state candidates, and unvalidated citations remain private.

Exit gate: first useful text timing and final persisted text are proven in a real browser; cancel,
timeout, and lease loss cannot mark undelivered text as learned.

## Slice 2 — Do One

Repair the existing UI/API/Question Engine path without adding another engine. Prefer an authorized,
compatible READY revision; generate only when reuse is impossible and an existing paid-call slot is
both applicable and available.

Exit gate: click, question, answer, score, answer reveal, explanation, history, and Pair restoration
all pass with one real Clerk student.

## Slice 3 — dynamic-K assessment

Derive K from versioned source-backed independently testable points, never from node count or READY
count. Reuse valid questions, prepare missing slots independently, and freeze only after all N slots
are qualified.

Exit gate: setup, preparation progress, open exam, submit, score, history, K=0, and legacy histories
pass; `K <= N <= 2K` and two-items-per-point are enforced server-side.

## Slices 4–7

Proceed in the package order. Each slice starts from the last verified commit, changes one logical
boundary, runs affected tests plus one real-path acceptance, receives review, and is committed before
the next slice begins. Production writes occur only inside a verified shared release window with a
fresh backup and rollback target.

## Current release risks

1. The Hangzhou production volume has only about 5.9 GiB free (94% used); no build, backup, or
   migration may start there before a safe space plan is verified.
2. RAG and Agent services expose different effective provider/feature values. Their actual call sites
   must be traced before any routing change.
3. Old RUNNING, RESERVED, and UNKNOWN rows exist. They are evidence, not permission to clear or retry.
4. The deployed release directory has no Git metadata, so file-level identity evidence is required.
5. The Singapore monitor service is failed even though the API tunnel is active; release monitoring
   must be restored or replaced before switching production.

