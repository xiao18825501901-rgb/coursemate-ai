# Exercise and Problem-step test report

Application release SHA: `46415bde81df28f4dc18629219bc9ddc50e4c215`

Live model: **VERIFIED — qwen3.8-max**

Production: **VERIFIED — qqttai.com**

## Exact-release local evidence

| Layer | Result |
| --- | ---: |
| Full RAG/backend regression | **692 passed**, 0 failed/errors/skipped; 746.81 s |
| Web tests | **60 passed** |
| Agent tests | **66 passed** |
| Web typecheck / production build | passed / passed |
| Agent typecheck / build | passed / passed |
| Main Playwright gate | **4 passed** |
| Complete browser audit | **14 passed**, 56.4 s |

The final backend XML is
`work/release-20260920-6e0b8d7/rag-pytest-restartfix.xml`. Its containing directory retains the
earlier candidate name, but the run itself was made after and against application SHA `46415bd`.
Browser evidence is under `work/codex-audit/browser-1789891592203-21556`.

The final SHA includes one additional restart-safety regression and repair. Production restart
revealed a teaching-only Pair whose Problem lane was null; migration incorrectly treated the null
lane as missing and attempted to recreate an already-bound Pair. A production-shaped regression
failed first, then `cm_update/db.py` was changed so a null lane is already satisfied and only
non-null conversations participate in the existing-conversation set. The full suite above was run
after that change.

## Live model evidence

The approved combined ceiling was USD 1.50. No call was retried automatically.

| Run | Calls | Input tokens | Output tokens | List-price estimate |
| --- | ---: | ---: | ---: | ---: |
| Isolated pre-release canary | 5 | 16,191 | 5,760 | USD 0.066942 |
| First production harness; browser JWT expired after completed calls | 2 | 6,572 | 2,280 | USD 0.026824 |
| Successful production API canary | 5 | 16,222 | 5,287 | USD 0.064166 |
| First browser preparation; model returned an insufficient step shape | 1 | 2,964 | 424 | USD 0.008472 |
| Successful browser preparation: four-step Problem plus saved detail | 2 | 6,349 | 2,220 | USD 0.026018 |
| LearningBridge teaching from the first visible Problem step | 1 | 967 | 165 | USD 0.002924 |
| **Total** | **16** | **49,265** | **16,136** | **USD 0.195346** |

The estimate uses USD 2 per million input tokens and USD 6 per million output tokens. It is not a
provider invoice. Every failed or superseded harness attempt is included in the total.

The production API canary verified:

- CS3481 generated exercise hidden before reveal, stable reveal and persisted explanation;
- GE2324 generated exercise hidden before reveal and stable reveal;
- CS3481 ordinary multi-step Problem plus saved explanation;
- strict response contract, exact provider call counts and no implicit retry.

The production browser acceptance then verified four visible Problem knowledge links, loaded the
saved detail, created a real LearningBridge teaching run, rendered the teaching response, returned
to the original Problem step and exposed no stored plan fields. Chrome reported one
`net::ERR_ABORTED` after the completed run event stream was intentionally closed by the page. This
occurred after all application assertions and screenshots passed; it was isolated from unexpected
network failures and is recorded rather than hidden.

Ignored evidence artifacts:

- `work/release-20260920-46415bd/production-canary.json`
- `work/release-20260920-46415bd/production-browser-preparation.json`
- `work/release-20260920-46415bd/production-browser-acceptance.json`
- `work/release-20260920-46415bd/production-ordinary-problem-steps.png`
- `work/release-20260920-46415bd/production-learningbridge-return.png`

## Production gate result

The previously open gates are now closed: current backup and isolated restore passed, the exact SHA
is active on both backend and frontend, public health and authentication boundaries pass, and the
paid-model browser workflow passes. The complete operational record is in
`PRODUCTION_HOTFIX_EXECUTION.md`.
