# OpenJev and P0 integration status

Date: 2026-09-29 (Asia/Shanghai)

## State matrix

| Layer | Status | Evidence |
|---|---|---|
| TypeSafe disabled in active paths | VERIFIED IN PRODUCTION | no `TYPESAFE_*` entries in active/inactive CourseJesus env files; RAG healthy after restart |
| Soft semantic dependency behavior | SOURCE IMPLEMENTED / TARGETED VERIFIED | disabled transport returns deterministic/off behavior rather than calling TypeSafe |
| OpenJev runtime installed | VERIFIED IN PRODUCTION | systemd active, private `/health`, `/ready`, `/version`, real inference |
| Model revision frozen | VERIFIED IN PRODUCTION | local manifest and per-file hashes returned by `/version` |
| 2C4G resource operation | VERIFIED FOR CONTROLLED LOAD | single instance, real inference and 3-client queue probe; not a claim of arbitrary throughput |
| Python `OpenJevTransport` | SOURCE IMPLEMENTED / OFFLINE CONTRACT VERIFIED | bearer, loopback/TLS restriction, pinned revision, no retry, language/output validation |
| Decision receipt metadata | SOURCE IMPLEMENTED / OFFLINE CONTRACT VERIFIED | provider/model/request/distribution stored inside existing receipt JSON |
| Four hard-gate quality | FAILED QUALIFICATION | all twelve held-out subgroups at 0.50 accuracy |
| Four hard gates enabled | NO | intentionally remain off |
| New adapter application release | NOT DEPLOYED | production application remains `b63401e`; only standalone runtime and TypeSafe isolation were deployed |
| Question READY live via OpenJev | NOT VERIFIED | blocked by quality qualification |
| P0 private/campus exercise recovery | NOT VERIFIED BY THIS RELEASE | no claim based on service health |
| Full assessment submit/grade/explain | NOT VERIFIED BY THIS RELEASE | no claim based on service health |
| Authenticated browser acceptance | NOT RUN FOR THIS RELEASE | runtime endpoint is server-private |

## Source implementation

The new `services/openjev-service` package provides:

- exact-commit vendoring and frozen model-manifest verification;
- loopback bearer-authenticated HTTP service;
- one-question bounded decisions with a single loaded model instance;
- real tokenizer limits and `truncation=error`;
- queue admission control and no implicit retry;
- systemd hardening and resource limits;
- a 240-case qualification runner.

The RAG application provides:

- `DisabledTransport` as the safe default;
- `OpenJevTransport` as the only new live semantic transport;
- fail-closed settings validation for endpoint, token, and model revision;
- preserved provider-neutral metadata in existing receipt storage;
- startup that never constructs legacy TypeSafe transport.

The legacy SDK adapter remains only for historical compatibility/tests. It is
not reachable through application startup and is not an automatic fallback.

## Verification completed

- OpenJev service tests: 8 passed
- OpenJev JavaScript syntax checks: passed
- OpenJev production dependency audit: 0 known vulnerabilities
- focused RAG/OpenJev/P0 regression: 42 passed
- prior combined focused run after fixture adaptation: 112 passed, 4 failed;
  three P0 failures were corrected and verified; the remaining assessment test
  represents the intentional hard-gate qualification block when semantic review
  is off, not permission to publish an unreviewed five-question set
- production: runtime ready, real inference, resource probe, RAG/Agent health,
  public RAG health all verified

The assessment test must be rewritten as two explicit contracts before a future
application release: fail-closed when no qualified judge exists, and READY when a
qualified fake/live judge returns valid durable receipts. It must not expect the
unqualified runtime to publish questions.

## Deployment boundary

The full dirty application worktree contains ongoing P0 assessment, streaming,
UI, and migration changes beyond OpenJev. Deploying it as one artifact would mix
unfrozen changes with an unqualified hard gate. Therefore this execution deployed
only the independently frozen OpenJev service and the production TypeSafe
isolation change. It did not redeploy the RAG source adapter or frontend.

## Current safe behavior

- Normal app startup cannot send a TypeSafe request.
- Soft optional semantic helpers remain deterministic/off.
- Hard Question Engine semantic gates remain unavailable rather than defaulting
  to positive.
- Existing READY questions, historical receipts, frozen assessments, user data,
  and course access are not relabeled or deleted.
- Campus courses remain installed because there is no evidence that removing them
  is necessary for OpenJev capacity.

## Remaining P0 blocker

The installed candidate is not accurate enough to authorize CourseJesus hard
decisions. Closing the full P0 generation/assessment objective requires a qualified
replacement or adapted model and a separately frozen application release, followed
by authenticated exercise and assessment acceptance. A successful runtime install
alone is not reported as P0 completion.
