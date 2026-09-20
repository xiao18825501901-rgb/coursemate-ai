# Exercise and Problem-step test report

Application release SHA: `6e0b8d733f26a3c588761cd1d2d402f372e413b2`  
Test environment: local isolated/synthetic databases; fake provider unless explicitly stated  
Live model status: **NOT YET RUN**  
Production status: **NOT YET DEPLOYED**

## Local evidence

| Layer | Result | Evidence |
| --- | ---: | --- |
| Exercise/provider/privacy focused tests | 16 passed | strict JSON Schema request, invalid/truncated fail-closed, stream privacy, reveal, explanation gate |
| Broader affected backend set | 76 passed | Problem/exercise/history/share/projection coverage |
| Parser/share/problem targeted follow-up | 5 passed | compatibility and frozen-sharing paths |
| Full RAG/backend regression | **691 passed**, 0 failed, 0 skipped | `work/exercise-hotfix-a92dc07/rag-pytest-final.xml`; 647.629 s |
| Web unit tests | **60 passed** | frozen application SHA |
| Agent tests | **66 passed** | frozen application SHA |
| Web typecheck | passed | frozen application SHA |
| Agent typecheck | passed | frozen application SHA |
| Web production build | passed | preflight + artifact scan; `build-info.json` names the frozen SHA and production origins |
| Agent build | passed | frozen application SHA |
| Browser audit | **14 passed** | `work/codex-audit/browser-1789887141769-8756`; 57.8 s |

The browser suite proves, with the actual React UI and integrated local backend:

- generated answer hidden across run polling, SSE, Pair and exercise GET;
- reveal persists across reload and displays the saved steps;
- an ordinary supplied Problem displays four steps rather than an empty pane;
- real 详解 buttons are visible and open a saved explanation;
- a real step-link creates LearningBridge context and the return action restores the Problem step;
- detail-window drag, resize, close and reopen keep saved state;
- user isolation, sharing and the surrounding UI regressions remain green.

Visual evidence for the ordinary Problem path is under
`work/codex-audit/browser-1789887141769-8756/browser-results/`; the inspected screenshot shows all
four solution steps and four LearningBridge knowledge actions.

## Preserved failed evidence

The first full run is retained at `work/exercise-hotfix-a92dc07/rag-pytest.xml`: 690 passed and one
failed. The only failure was an old synthetic-provider assertion that still expected exactly two
steps after the fixture was intentionally expanded to four to reproduce the production UI defect.
The assertion was updated to the new deterministic fixture contract, the application commit was
amended, and the complete suite was rerun against the new frozen SHA. The fresh XML above is the
release evidence; the earlier failure was not deleted or rewritten.

An initial Playwright launch also used an evidence directory outside the harness-required
`work/codex-audit` root. The harness rejected the environment before application tests ran. The
suite was then run in the required isolated directory and passed 14/14; the rejected launch is not
reported as an application pass or failure.

## Gates still open

The following may only be marked passed after new evidence is attached:

1. bounded real `qwen3.8-max` canary for CS3481 generated exercise, reveal and explanation;
2. bounded GE2324 generated exercise and reveal;
3. bounded ordinary multi-step Problem, visible saved steps and explanation;
4. current production backup plus isolated restore verification;
5. exact-SHA backend switch and Netlify production publish;
6. public health, auth/isolation, browser and paid-model production smoke.

