# Exercise runtime contract v2

Status: **SOURCE, OFFLINE CONTRACT, LIVE MODEL AND PRODUCTION VERIFIED**

Application release SHA: `46415bde81df28f4dc18629219bc9ddc50e4c215`

Runtime identifier: `exercise.v2`

This contract is the application-facing output contract for the **做一题** action. It is deliberately
separate from the owner-supplied teaching Word template, which remains read-only course input. The
contract is enforced at the Qwen boundary and again by the server before persistence.

## Provider request

- Provider/model: Alibaba Cloud Model Studio `qwen3.8-max`.
- Endpoint family: OpenAI-compatible Chat Completions.
- Output mode: `response_format.type=json_schema`, strict schema.
- Streaming: enabled, but raw structured deltas are buffered server-side and never forwarded to the
  browser.
- Provider-native thinking: disabled for this structured operation.
- Retry policy: no implicit retry. A failed/truncated/invalid response ends the run and requires a new
  explicit user action and request ID.

The accepted object has exactly these top-level fields:

```json
{
  "question": "complete student-facing question, without answer",
  "answer_steps": [
    {
      "title": "short step title",
      "text": "private answer step"
    }
  ],
  "references": ["S1", "S2"]
}
```

Server validation requires:

- a bounded non-empty `question`;
- 1–20 bounded, non-empty answer steps;
- exact step keys only;
- reference identifiers matching `S<number>` and belonging to the authorized source set supplied to
  the model;
- no unknown top-level fields.

The model does not control persistent step identity. The server derives a deterministic `step_id`
from the validated answer version and step content.

## Privacy and publication boundary

Before reveal, the only public exercise content is `question`:

- run polling returns the question as `partial_text`;
- SSE suppresses all structured answer fragments and emits only the completed question;
- Pair/conversation history returns an exercise with `revealed=false` and `steps=[]`;
- the exercise endpoint returns `steps=[]`;
- step-explanation creation returns HTTP 403.

The complete validated answer is stored only in the server-owned exercise row. Reveal is an
idempotent persisted user action and does **not** call the model. After reveal, the same saved step
version is returned, survives refresh/login, and is the only version used by step explanation.

References persisted with an exercise are the server's authorized citation metadata for the selected
source IDs. Raw model-provided source text or paths are not trusted as authority.

## Exercise source classification

`source` is server-derived:

- `generated`: a versioned diagnostic exercise, an explicit 做一题 run, or a message whose public
  content is the stored generated question;
- `user_problem`: an ordinary user-supplied Problem request whose full solution is already intended
  for immediate display.

The provider cannot set this value. Generated exercises stay hidden until reveal; ordinary Problem
solutions remain visible with their parsed steps and LearningBridge actions.

## Compatibility

Historical `exercise.v1` delimiter records remain readable through a fail-closed compatibility
parser. Missing, duplicate, ambiguous, or stream-split markers never cause an answer to be exposed.
All new Qwen 做一题 generation uses `exercise.v2`.

Production acceptance on 2026-09-20 verified the contract with real `qwen3.8-max` calls in both
CS3481 and GE2324. Before reveal, generated answers remained absent; reveal returned the persisted
steps without another provider call; a saved step explanation completed. The provider invoice was
not accessed, so recorded USD values are list-price estimates derived from returned token usage.

## Code and test anchors

- Schema/validator: `services/rag-api/app/cm_update/exercise_contract.py`
- Versioned provider instruction: `services/rag-api/app/cm_update/prompts/EXERCISE_RUNTIME_CONTRACT_V2.txt`
- Provider request: `services/rag-api/app/cm_update/provider.py`
- Persistence/public projection/reveal: `services/rag-api/app/cm_update/app.py`
- Contract tests: `services/rag-api/tests/ui_extension/test_exercise_contract.py`
- Privacy/API tests: `services/rag-api/tests/test_codex_exercise_privacy.py`
