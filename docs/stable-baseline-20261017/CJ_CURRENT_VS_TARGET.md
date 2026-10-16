# Current production versus stable-baseline target

## Proven current production

The current browser build is Netlify deploy `6ad0d52476d6671ce3d8fe6c`. Its title identifies
`deb82cc518b2`, and six runtime-critical backend source files match that local commit byte for byte.
Rebuilding the Agent from the lockfile also reproduced the deployed JavaScript SHA-256 exactly.

The public browser does not use the old `rag.qqttai.com` record. The deployed bundle points to
`rag.47-237-179-69.sslip.io`, where Singapore terminates TLS and tunnels to the active Hangzhou
services. That route is healthy. The old qqttai hostnames currently reset TLS connections and must
not be mistaken for the live browser route.

## Current measurable behavior

| Signal | Current evidence | Target evidence |
|---|---:|---|
| CourseJesus homepage TTFB | 0.59–1.08 s (3 samples) | keep within the current range or improve |
| RAG public health TTFB | 0.33–1.01 s (3 samples) | no regression after every release |
| Agent public health TTFB | 0.26–0.58 s (3 samples) | no regression after every release |
| Do One stored wall time | mean 10.55 s, max 28.03 s, 30 completed runs | measure click-to-question and make the normal reuse path reliably fast |
| General stored wall time | mean 79.47 s, max 643.59 s, 109 completed runs | measure and materially reduce first useful text without model downgrade |
| First useful student text | not recorded by current schema | capture in a real browser before and after R1 |

Stored run duration is not a substitute for browser TTFRT. Zero-duration rows are retained rather
than discarded, so the aggregate is descriptive evidence, not a performance SLA.

## Gaps between current behavior and target

1. The current UI event reader consumes SSE correctly, but the existing server path still persists
   and publishes final/partial state through a mixed orchestration path. R1 must prove that only safe
   student text is emitted early and that private planning/state candidates never cross the boundary.
2. Do One already has a separate exercise API, evaluation, reveal, explanation, and history path.
   Its cold author contract, however, explicitly permits only DeepSeek receipts or labelled fixtures.
   That is incompatible with the accepted general-role Qwen target and must be changed at the trusted
   provider identity boundary rather than by weakening the output schema.
3. Assessment setup and session APIs exist, including preparation status and history. Dynamic-K is
   disabled in the effective RAG environment, so the current production behavior cannot establish
   that source-backed K is used.
4. RAG runs with DeepSeek-oriented legacy settings while the Agent service carries Qwen/generic-role
   settings. This is a real split configuration, not proof that every general role is migrated.
5. The active UI bundle exposes the configured model through a `model-label` element. That conflicts
   with the requirement to hide provider/model names in system UI.
6. The dependency lock currently reports one critical and one high advisory. Reachability and the
   smallest compatible fix must be resolved before any candidate is released.
7. Production has old RUNNING, RESERVED, and UNKNOWN records. They remain immutable evidence; stage
   logic must avoid turning them into a global lock for new, independently identified operations.

## Release boundary

No release is currently authorized or safe. The Hangzhou disk is 94% full, Singapore monitoring is
failed, the dependency audit gate is red, and real-browser TTFRT plus isolated-data compatibility are
not yet proven. These are concrete release conditions, not a request to redesign the product.

