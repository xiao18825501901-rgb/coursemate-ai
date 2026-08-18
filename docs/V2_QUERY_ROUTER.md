# CourseMate AI V2 Query Router and Teaching Orchestration

Status: implemented and locally verified on branch `feature/coursemate-v2-ai-tutor`.

## Intent contract

The deterministic router selects one of five strategies before retrieval:

| Intent | Retrieval | Answer policy |
|---|---:|---|
| `COURSE_GROUNDED` | yes | Claims must be supported by retrieved course evidence; insufficient evidence returns the existing refusal. |
| `COURSE_TUTORING` | yes | Course evidence may be combined with clearly labeled supplementary explanation; citations support only retrieved evidence. |
| `GENERAL_CONVERSATION` | no | Natural study-support conversation without a fake RAG refusal or invented citation. |
| `COURSE_META` | no | Uses trusted course/document metadata rather than semantic retrieval. |
| `AMBIGUOUS` | yes | Uses course evidence cautiously and asks a concise clarifying question when needed. |

Explicit evidence language such as “课件中”, “according to lecture”, and “老师的 slides” takes precedence over generic teaching words. Social/study-support phrases bypass retrieval. Teaching, example, why, and confusion phrases select tutoring. Uncertain subject-only queries retain the conservative course-aware path.

The router is heuristic by design: it is deterministic, explainable, free of paid classifier calls, and covered by Chinese/English tests. It is a strategy selector, not a claim that natural-language intent can be perfectly classified.

## Multi-turn retrieval rewrite

The original user message is always persisted unchanged. Only the retrieval query is rewritten. Short follow-ups such as “为什么？”, “what about that?”, and “我还是不懂” are joined to the most recent standalone user topic with a 320-character bound. Repeated confusion turns skip previous follow-up phrases so the original topic is not lost.

Up to 12 recent user/assistant messages are provided to the answer model inside explicit `UNTRUSTED CONVERSATION HISTORY` delimiters and a 2,000-character budget. They remain lower priority than platform and tutor policies.

## Progressive teaching

For `COURSE_TUTORING`, recent confusion signals change the approach:

```text
no confusion       -> formal/intuitive explanation
first confusion    -> concrete analogy
second confusion   -> small worked example
third+ confusion   -> short Socratic diagnosis
```

The approach is part of trusted instructions and returned in SSE metadata. The system does not mechanically force all teaching headings on simple questions.

## Grounding transparency

The additive SSE `meta` fields are:

```json
{
  "queryIntent": "COURSE_TUTORING",
  "groundingMode": "mixed",
  "retrievalQueryRewritten": true,
  "teachingApproach": "analogy"
}
```

Existing events and fields are unchanged, so older clients can ignore the additions. The web UI displays a per-answer label:

- Course-material answer
- Course material + AI knowledge
- General tutor conversation
- Course information

Mixed answers state that citations support only the course-material portion. General answers state that no course-grounding claim is implied.

Database migration version 3 additively adds `messages.metadata_json`, defaulting legacy messages to `{}`. New assistant messages store the same routing metadata that was streamed. Therefore each label survives refresh and old-conversation recovery without reclassifying historical text.

## Security boundaries

- Retrieved documents and conversation history are untrusted prompt context.
- General model knowledge is never represented as a citation.
- `COURSE_META` context is generated from server-side database rows and capped at 100 document entries.
- Course and conversation ownership checks happen before orchestration.
- The model never controls routing authorization, user identity, course ID, or SQL.

## Verification evidence

Verified on 2026-08-13:

```text
RAG API: 81 pytest tests passed
RAG lint: ruff passed
RAG types: mypy passed for 30 source files
Web: 17 Vitest tests passed
Agent API: 47 Vitest tests passed
Web + Agent type checks passed
Web production build passed
```

Coverage includes five-way routing, precedence, short and repeated follow-up rewriting, bounded history, prompt hierarchy, general chat on an empty course, mixed tutoring on an empty course, metadata questions, progressive multi-turn strategy, routing metadata persistence, route refresh, and citation compatibility.

No paid model call or production change was made for this stage. Model-quality scoring remains owned by the Stage 4/5 eval and benchmark gates.
