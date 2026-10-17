# Dashboard 三入口与练习测评恢复增量规格

## Objective

在当前稳定基线 `928327d331d6767ead5c51c8b54424060718d160` 上分两次发布：

1. 先将 Dashboard 的三个真实入口改为标题分隔线下方、同一行三等宽虚线卡片；保留原 Canvas、创建课程和所有课程回调。
2. 再解除“做一题”和“开始测评”对方法资格、人工 Gold、多轮模型审核及 OpenJEV 审批的同步依赖，同时保留认证、来源、题目完整性、答案隔离、幂等、账本、旧成绩与 UNKNOWN 保护。

本规格由 Owner 上传的 `CourseJesus_Dashboard_Exercise_Recovery_20261018.zip` 与最高优先文件 `02_CODEX_先发布三入口再恢复练习测评_CN.md` 批准。

## Tech stack and commands

- Frontend: React/Vite, `apps/web/src/ui`。
- Backend: FastAPI/Python, `services/rag-api`。
- Frontend tests: `npm --workspace apps/web test -- --run <test>`。
- Type check: `npm run typecheck`。
- Production build: `npm run build`，必须注入现有 Netlify production VITE 环境。
- Backend targeted tests: `python -m pytest -q <paths>`。

## Project structure

- Dashboard component and styles: `apps/web/src/ui/`。
- Dashboard host wiring: `apps/web/src/ui/App.jsx`。
- Locale keys: `apps/web/src/ui/locales/{zh-CN,en}.json`。
- Practice/assessment policy and host integration: existing `services/rag-api/app/learning` and `app/ui_extension` modules only。
- Evidence and receipts: `docs/stable-baseline-20261017/`。

## Code style

- Reuse existing `Icon`, `goto`, `canvasImport`, `createCourse`, `t()` and theme tokens。
- Prefer additive, typed interfaces and existing service boundaries；不创建第二题库、评分服务、账本、微服务或 locale store。
- UI controls use native `button type="button"`, accessible group label and visible `:focus-visible` state。

## Testing strategy

- RED: first change dashboard tests so the current two large cards + bottom link fail the new layout contract。
- GREEN: add the smallest component/CSS/locale/host wiring to pass component tests, typecheck and production build。
- Browser: inspect the real authenticated production page at desktop and mobile widths, verify callbacks and no overflow。
- Backend: reproduce both reported readiness messages, add boundary tests, fix the current host/service path, then run targeted and affected regression suites。
- E2E: use a real Clerk student, original failing course/node and a second cold-start course；HTTP 200/202 alone is not PASS。

## Boundaries

- Always: preserve Clerk authorization, source ownership, answer/rubric privacy, deterministic field checks, idempotency, costs, UNKNOWN records, existing attempts/scores/history and rollback identity。
- Ask only if genuinely missing: new paid-provider authority beyond current product budget, unavoidable MFA/login, destructive schema/data action, or a conflicting live production lock。
- Never: replay UNKNOWN, fake QUALIFIED/READY, publish `preview/index.html`, build without production VITE values, reset/clean shared worktrees, replace production DB, touch NanoJEV/ComfyUI。

## Success criteria

- UI release: three equal-width dashed cards appear immediately after the dashboard header separator in desktop and mobile; all three invoke their existing real actions; old dashboard duplicates are gone; authenticated zh-CN/en and dark/light work; backend/schema unchanged。
- Practice release: an original quality-pending node can generate/reuse one source-grounded complete question, accept an answer, grade it, reveal answer/explanation and restore history without whole-catalog or formal qualification approval。
- Assessment release: an original quality-pending scope derives or prepares real K, configures `K <= N <= 2K`, prepares only missing complete questions, opens, submits, grades and restores history without formal qualification approval; legacy scores remain unchanged。
- Source-missing/revoked and unauthorized cases still fail closed; incomplete or explicitly wrong questions never publish。

