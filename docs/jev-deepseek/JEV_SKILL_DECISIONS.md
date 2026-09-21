# Jev Skill and Ecosystem Decisions

## Official-source verification (2026-09-21, this execution)

| Source | Reachable | Recorded |
|---|---|---|
| `https://github.com/typesafe-ai/skills/blob/main/skills/typesafe-ai/SKILL.md` | ✅ reachable (raw `SKILL.md` fetched, HTTP 200) | front-matter `license: MIT`; skill blob previously recorded as `0109513f9656917dc93cbc5ecddfca465a53ce66` in the pack. |
| `https://docs.typesafe.ai/llms.txt` | ✅ reachable (index referenced; targeted `.md` pages fetched) | — |
| `https://docs.typesafe.ai/sdk/python.md` / `primitives.md` / `confidence.md` / `usage.md` | ✅ reachable (Markdown fetched) | SDK usage verified below. |
| `https://github.com/typesafe-ai/typesafe-sdk-python` | ✅ reachable via PyPI metadata | `typesafe-sdk` **0.7.0**, MIT, "Python SDK for TypeSafe AI API". |

### Verified SDK contract (only these fields are used)

```python
from typesafe_sdk import TypeSafeClient, AsyncTypeSafeClient, Choice, Noul, Score

client = TypeSafeClient(model="jev")                     # model selection (verified)
result = client.system_one(state, questions)             # state: dict|str, questions: dict
# Choice(instructions=..., criteria={"opt": None})
# Score(instructions=..., criteria=["low","med","high"])
# Noul(instructions=...)
result.choices[key].choice                               # selected option id
result.scores[key].score                                 # selected level
result.nouls[key].noul                                   # probability float in [0,1]
result.request_id
# TYPESAFE_API_KEY env var; TypeSafeAPIError(.status, .request_id)
```

**UNKNOWN / not invented**: the exact `.score` return type (level key vs index vs
description) is not pinned in the fetched docs, so `gateway._validate` tolerates
level keys, 0-based indices and level descriptions. No `/evaluate` endpoint, no
model id other than the documented `model="jev"` default, no timeout/limit value,
and no retry configuration is assumed. The SDK is **lazily imported only inside
`SdkTransport`** and is not a runtime dependency: the app runs fully without it,
and the live path raises `JEV_NOT_CONFIGURED` when `TYPESAFE_API_KEY` is absent.

## Dependency decision (NO new runtime dependency)

* `typesafe-sdk` (`0.7.0`, MIT) is the only new third-party package and is
  **optional / lazy** — it is never imported at package load, so the production
  wheel has no new hard dependency. It is listed here for pinning if the live
  path is ever enabled: `typesafe-sdk==0.7.0` (MIT).
* Everything else in `app/jev/` is stdlib (`dataclasses`, `json`, `hashlib`,
  `threading`, `concurrent.futures`, `sqlite3` via `app.db`).

## The 20 ecosystem items (plan §7 / §16)

"Adopted pattern" = the *idea* is implemented inside this repo's narrow Jev layer
(`app/jev/`); "not installed" = no third-party code, server, or new service was
added.

| # | item | adopted pattern | where used here | why not installed |
|---|---|---|---|---|
| 1 | jev-ultrafast | dev-only navigation helper | not used | test assertions stay deterministic (pytest/Playwright); no dev browser tool. |
| 2 | fast-jev-compaction | keep original text, drop only optional history | `context.keep_segment.v1` (service helper) | fixed anchors/permanent history are never dropped by our code. |
| 3 | json-render | fixed teaching/assessment component choice only | `template.match.v1`, `pedagogy.next_method.v1` (helpers) | no full-site generative UI. |
| 4 | typesafe-mcp | dev tool; production calls SDK directly | not used | adds an MCP hop for zero benefit. |
| 5 | jev-mcp | ranking/checking pattern | `retrieval.support.v1`, `source.supports_claim.v1` | implemented as the narrow internal service, no MCP server. |
| 6 | SemDecide | offline document/question screening | `corpus.quality.v1` (helper) | never deletes originals. |
| 7 | jev-codex-router | dev task complexity/test routing only | not used | must not touch user billing tiers. |
| 8 | Winnow | single context selector | `context.keep_segment.v1` | avoid a second memory system. |
| 9 | jev-review | risk diff triage | not used | real tests + review evidence, not a model verdict. |
| 10 | Blink | source-candidate navigation | not used | DSH reads full relevant code itself. |
| 11 | agent-desktop | — | not used | would bypass the owner's login/MFA. |
| 12 | typesafe-mario | state → action separation | gateway `off/shadow/on` + deterministic fallback | no game features. |
| 13 | jev-drone | semantic decision / deterministic execution split | the whole `app/jev/` + `service` fallback design | no device control. |
| 14 | OneVOneJev | — | not used | no teaching need. |
| 15 | jev-trader | — | not used | trading demo proves nothing educational. |
| 16 | Prism | judge state, let code execute | `service.py` returns a value; call sites execute | no trading logic. |
| 17 | neo4jev | bounded graph traversal over existing nodes/prereqs | `graph.prerequisite.v1` (helper) | no Neo4j. |
| 18 | jev-curate | quality/source marking for docs/questions/exam sets | `corpus.quality.v1`, `source.select_span.v1` | keeps review records, no auto-publication. |
| 19 | Canny | completion claim ↔ evidence consistency | receipts (`jev_decision_receipts`) carry outcome/latency | final PASS stays a real product, not a model. |
| 20 | killmyidea | counter-evidence questioning (only if a course needs it) | not used | no site-wide judgment; student grades unaffected. |

**Bottom line**: 0 of the 20 third-party projects are installed; the adopted
behaviors are re-expressed inside the single `app/jev/` layer plus the two wired
call sites in `app/ui_extension/domain.py`.
