# CourseMate AI Verification Report

Verified on 2026-08-12 in deterministic provider mode unless stated otherwise.

## Release status

The local product, indexed corpus, automated behavior, production builds, and deployment descriptors are verified. Public internet deployment is intentionally gated on external authentication, billing, identity/access-control, Git hosting, OpenAI connectivity, and course-material authorization.

## Corpus and persistence evidence

| Check | Result |
|---|---|
| Read-only source inventory | PASS: 86 files; CS3481 50, GE2324 36; missing `tut7` and `tut8` recorded |
| Supported imports | PASS: 66/66 ready; CS3481 38, GE2324 28; zero failed |
| Indexed chunks | PASS: 1,936; CS3481 924, GE2324 1,012 |
| Inventory-only assets | PASS: 20 legacy/data files explicitly retained outside prose retrieval |
| Browser-test cleanup | PASS: 6 generated conversations removed; 0 conversations/messages remain; documents/chunks unchanged |
| Scanned assignment remediation | PASS: SHA-256-bound, reviewed transcription applied only to the matching `assignment_2.pdf` |

## Automated verification

| Gate | Result |
|---|---|
| FastAPI/RAG pytest | PASS: 42 tests |
| Python Ruff | PASS |
| Python strict mypy | PASS: 25 application/import-script source files in the delivery command; 31 app/test files in the service-local command |
| Python dependency check | PASS: no broken requirements |
| React/Vitest | PASS: 4 files, 8 tests |
| Agent/Vitest | PASS: 6 files, 32 tests |
| TypeScript type checks | PASS: Web and Agent |
| Production build | PASS: Agent compiled; Web bundle 254.79 kB JavaScript / 80.19 kB gzip, 16.05 kB CSS / 4.00 kB gzip |
| Chrome/Playwright | PASS: 3/3 end-to-end scenarios; no browser console warnings/errors |
| npm audit | PASS: 0 vulnerabilities at high threshold |
| Lockfile reproducibility | PASS: clean `npm ci --ignore-scripts` completed under Node 24.14; no native addon install chain |
| Deployment descriptor parsing | PASS: `netlify.toml` and `render.yaml` parse successfully |
| Git whitespace check | PASS |

The Playwright scenarios cover cross-course switching, streamed cited QA, `assignment_2.pdf` as the first assignment citation, answer-to-plan, natural-language task creation, direct edit, completion, persistence within the run, responsive navigation at 390 px, and browser-console cleanliness. After the reporter completed all three scenarios, the local PTY wrapper required an interrupt; exact port/process inspection confirmed that 5173, 8000, and 8001 were stopped.

## Real-corpus retrieval probes

| Course/question | Observed evidence |
|---|---|
| CS3481: DBSCAN core point | `Cluster Analysis...pdf`, pages 32 and 29 |
| GE2324: Spearman correlation | `Topic05_[CourseSlides]Correlation.pptx`, slides 68 and 87 |
| GE2324: MinHash similarity | `Topic04_[CourseSlides]ClusteringAnalysis.pptx`, slide 17; `ge2324_assignment_3.pdf`, page 2 |
| GE2324: Assignment 2 K-means/colors | First fused result is `assignment_2.pdf`, page 1; second result is also the checksum-bound assignment transcription |

Every probe was asserted against the selected course, and the assignment query has unit, fusion, full-corpus, and real-browser regressions.

## Security and privacy review

- OpenAI credentials are server-only; no key is embedded in frontend configuration.
- Targeted repository/delivery-document scanning found no assigned `OPENAI_API_KEY` or credential-shaped `sk-...` value.
- Upload validation covers allow-listed extensions, size, content signature, generated storage names, SHA-256 duplicate checks, and controlled errors.
- SQL uses parameterized prepared statements; tool calls are allow-listed and strictly validated with `additionalProperties: false`.
- CORS, Helmet, JSON size limits, and rate limiting are configured.
- `data/uploads`, populated SQLite databases, `.env`, build output, caches, and `work/` are ignored. Git tracks only the import report and the checksum-bound transcription needed to explain the scanned-PDF remediation.
- The APIs do not yet have an end-user identity layer. Authentication or platform-level access control is mandatory before public exposure.

## Known, bounded warnings

- Node 24.14 reports `node:sqlite` as experimental. ADR-002 pins the runtime and records the portability decision; all repository, API, and tool behavior is covered by tests.
- FastAPI TestClient emits one upstream Starlette deprecation warning recommending `httpx2`; application tests still pass.
- The host also has Node 18 and stale Python launcher entries. The project pins Node 24.14+ and uses its repository virtual environment; `scripts/start_local.ps1` rejects an older Node before starting.

## External gates not claimed as passed

1. A live OpenAI probe could not reach an HTTP response because the current network path timed out/reset during TLS connection. This does not validate or invalidate the secret/model; deterministic adapters verify the application logic.
2. `git remote -v` is empty, so no hosting provider can deploy this repository yet.
3. The bounded Netlify CLI status attempt stalled during package resolution and produced no authenticated status. No interactive login was launched.
4. Render requires an authenticated account, approval for two paid Starter services and persistent disks, and secret entry.
5. The operator must select an end-user authentication/access-control approach.
6. The material owner must authorize any production upload or public exposure of the supplied course files.

No public URL is reported because these external/security gates remain unresolved. `netlify.toml`, `render.yaml`, `docs/DEPLOYMENT.md`, health checks, environment aliases, empty production-disk initialization flow, CORS close-loop, acceptance steps, and rollback instructions are ready for the authorized deployment session.
