# CourseJesus stable-baseline upgrade specification

## Status

Accepted for implementation. The Owner-supplied package
`CourseJesus_Stable_Baseline_Upgrade_20261017.zip` is the controlling product specification.
This document records the repository-local interpretation and does not replace that package.

## Objective

Restore a small, stable CourseJesus production baseline in seven bounded releases while preserving
all current student data, historical assessments, billing/audit records, and UNKNOWN operations.

## Required student capabilities

1. Knowledge learning with safe incremental public text.
2. Course knowledge tree with at most 50 displayed nodes and a valid Teaching Spec.
3. Do One: obtain/reuse a question, answer it, receive scoring, reveal the answer and explanation,
   and reopen history.
4. Problem response: submit a student problem and receive a useful explained result.
5. Dynamic-K assessment: derive independently testable points, configure `K <= N <= 2K`, prepare
   only valid questions, submit, score, and reopen original history.
6. RAG upload, retrieval, citations, course isolation, and access control.
7. OpenJEV as a non-blocking advisory capability where the historical path genuinely used it.

## Invariants

- Private-course knowledge-tree generation remains on the verified DeepSeek path.
- General LLM work uses only the currently authorized server-side provider configuration.
- No provider secret, Clerk cookie, private source text, or model reasoning appears in client output,
  logs, evidence, commits, or reports.
- No old UNKNOWN request is replayed, renamed, or globally cleared.
- No production database is replaced by a historical copy and no destructive reverse migration is
  run against production.
- Historical questions, answers, marks, scores, catalog versions, and histories are immutable.
- NanoJEV and ComfyUI are outside this upgrade and must not be changed.
- Each release is independently testable and independently reversible.

## Delivery stages

- S0: read-only identity, topology, data compatibility, baseline latency, and dependency trace.
- R1: safe streamed learning/problem-response content.
- R2: stable Do One, preferring compatible READY questions.
- R3: dynamic-K assessment preparation and complete student loop.
- R4: isolate map/index/preparation work from interactive learning; retain RAG correctness.
- R5: reconcile model-role routing without changing the private-tree exception.
- R6: finish the accepted teaching-template, i18n, model-name hiding, and OpenJEV boundary work.
- R7: remove only proven dead or duplicate runtime paths, then freeze and release the candidate.

## Completion evidence

Production completion requires an immutable code SHA, frontend deploy ID, backend release identity,
schema identity, backup and rollback receipts, real Clerk student traces for all seven capabilities,
and post-deploy health and data-integrity checks. Unit-test counts alone are not acceptance.

