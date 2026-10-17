# Dashboard 三入口与练习测评恢复实施计划

## Phase A — UI independent release

### Task A1: Dashboard contract test (RED)

- Acceptance: tests require one action group directly after the page header, order Canvas/Create/All, three existing callbacks, no old add cards or bottom all-courses link。
- Verify: targeted Vitest fails on current `928327d` for the expected layout assertions。
- Files: existing dashboard tests only。

### Task A2: Component, locale and host wiring (GREEN)

- Acceptance: component uses three equal grid columns, mobile remains one row without overflow, i18n/theme tokens and existing handlers are reused。
- Verify: targeted tests, locale parity, typecheck and build pass。
- Files: component/CSS, `App.jsx`, two locale JSON files, tests。

### Task A3: Production-config build and frontend-only release

- Acceptance: frozen build contains existing Clerk/API public configuration and no secret; deploy goes to existing Netlify site with backend/schema unchanged; real Clerk desktop/mobile callbacks pass。
- Verify: deploy/read-back asset hash, authenticated screenshots, console/network check and rollback receipt。

## Phase B — Practice and assessment recovery

### Task B1: Reproduce and trace both entry failures

- Acceptance: exact frontend key, API code, readiness/host decision, question availability decision and open consumer are mapped separately for practice and assessment。
- Verify: targeted tests reproduce current qualification-pending rejection before code changes。

### Task B2: Practice vertical slice

- Acceptance: a source-grounded node can reuse or prepare one complete question without catalog/formal qualification; auth/source/privacy/idempotency boundaries remain enforced。
- Verify: policy/service tests plus real Clerk click → question → answer → score → reveal → history。

### Task B3: Dynamic-K assessment vertical slice

- Acceptance: `K=null` while preparing, K derives from current source/Spec, configuration precedes generation, only missing slots are prepared, N questions open only when structurally complete, and legacy attempts are untouched。
- Verify: K1/K2/K3 boundary tests plus real original failing scope and a second cold course through config → prepare → open → submit → grade → history。

### Task B4: Backend release and acceptance

- Acceptance: backup/space/lock/runtime checks pass; code-only release preserves schema/data; production student journeys pass or rollback occurs without DB replacement。
- Verify: immutable SHA, service/health identity, Clerk evidence, costs and rollback receipt。

## Phase C — resume R7

- Continue evidence-based pruning only after both student entry paths pass in production. Zero deletion is valid when no candidate meets no-reference + replacement + recovery criteria。

## Risks and mitigations

- Netlify production env omission: read existing env metadata and verify frozen bundle before deploy。
- Connected-main overwrite: record source SHA/deploy and integration requirement; do not push stale main blindly。
- Qualification removal broadens unsafe content: remove only formal approval gates; retain auth, source binding, complete reference/rubric, privacy, deterministic invalid/withdrawn rejection。
- Historical UNKNOWN duplication: preserve and reconcile by original operation identity; never resend it under a new ID。
- Active production operation: inspect live attempts/leases and lock before backend switch; do not infer safety from age alone。

