# BASELINE_AND_SOURCE_ROOT

## 1. Directory identification (actual, verified 2026-09-18)

| Symbol | Path | Evidence |
|---|---|---|
| ARCHIVE_ROOT | `D:\CourseMate_COMPLETE_ARCHIVE_20260918` | user-specified project scope |
| **ACTUAL_SOURCE_ROOT** (modified this round) | `D:\CourseMate_COMPLETE_ARCHIVE_20260918\01_SOURCE_REPOSITORY` | contains `.git`, `package.json`, `apps/`, `services/`, `docs/`; named the source of truth in `README_ARCHIVE.md`; robocopy copy of the original C-drive repository |
| FRONTEND_ROOT | `01_SOURCE_REPOSITORY\apps\web` | React + Vite app |
| RAG_BACKEND_ROOT | `01_SOURCE_REPOSITORY\services\rag-api` | FastAPI backend (main API + cm_update UI API + ui_extension) |
| AGENT_BACKEND_ROOT | `01_SOURCE_REPOSITORY\services\agent-api` | Node task-agent backend |
| GIT_ROOT | `01_SOURCE_REPOSITORY` | full git history, 14 refs |
| CURRENT_COMMIT | `c67904b27bd4b8c019d6b781999be4055283dbc6` | `release/openapi-fix` |
| CURRENT_SCHEMA (migrations) | up to `024_official_knowledge_generation_plans.sql` | `services/rag-api/migrations` |
| UI database schema version | 5 | `services/rag-api/app/cm_update/db.py` `SCHEMA_VERSION` |
| Local dev database (NOT authoritative) | `01_SOURCE_REPOSITORY\data\rag.sqlite3` (schema 18 fixture) | used only for local boot tests |

Other copies in the archive are explicitly NOT the modification target:
- `02_ORIGINAL_DSH_DELIVERY` = original DSH hand-off package (history only).
- `05_PRODUCTION_RELEASE_METADATA\5ba6a3a` = production release source snapshot (deployment artifact, read-only reference).
- `04_PRODUCTION_SNAPSHOT\*.sqlite3` = production database snapshots (read-only evidence; never run a dev server against them).

## 2. Working-copy protection

- Original C-drive repository (`C:\Users\Hp\Documents\Codex\...\coursemate-ai`) is NOT touched this round.
- Pre-change git marker: branch `archive-baseline/pre-change-20260918` at `c67904b` (created before any modification).
- Template extraction staging lives in `work\current-change\` (gitignored, outside compile/test paths).
- No production credentials, databases, or paid model calls are used during development.

## 3. Word template sources (read-only import)

Source dir: `C:\Users\Hp\xwechat_files\wxid_lpdn28neu0i112_ecd6\msg\file\2026-09`

| File | Role | Status |
|---|---|---|
| `01_研究生_商务资讯系统_…docx` … `14_本科_能源_…docx` | 14 professional templates | extracted (bodies 11.9–12.3K chars each, unique sha256) |
| `做一题prompt.docx` | exercise-generation prompt | extracted (2,893 chars body) |
| `题目prompt.docx` | direct problem-answer prompt | extracted (2,862 chars body) |
| `详解prompt.docx` | step-explanation prompt | extracted (2,731 chars body) |
| `CS3481.doc` | original CS3481 template (binary OLE2, read via Word COM, read-only) | extracted (3,450 chars) |

Extracted resources (runtime copies, do not depend on the WeChat path):

```
services/rag-api/app/learning/prompts/
  01_GRAD_BUSINESS_INFORMATION_SYSTEMS_V1.txt
  02_GRAD_COMPUTER_SCIENCE_V1.txt
  03_GRAD_DATA_SCIENCE_V1.txt
  04_GRAD_ELECTRONIC_INFORMATION_ENGINEERING_V1.txt
  05_GRAD_ENGINEERING_MANAGEMENT_V1.txt
  06_GRAD_MATERIALS_ENGINEERING_NANOTECH_V1.txt
  07_GRAD_BIOMEDICAL_ENGINEERING_V1.txt
  08_GRAD_ARTIFICIAL_INTELLIGENCE_V1.txt
  09_GRAD_BUSINESS_DATA_ANALYTICS_V1.txt
  10_GRAD_INNOVATION_ENTREPRENEURSHIP_V1.txt
  11_UG_COMPUTER_SCIENCE_TECHNOLOGY_V1.txt
  12_UG_INTELLIGENT_MANUFACTURING_V1.txt
  13_UG_MATERIALS_V1.txt
  14_UG_ENERGY_V1.txt
  15_OTHER_GENERAL_V1.txt            (Appendix A)
  CS3481_ORIGINAL_TEMPLATE_V1.txt   (original CS3481.doc full text)
  EXERCISE_PROMPT_V1.txt            (做一题)
  PROBLEM_PROMPT_V1.txt             (题目)
  EXPLANATION_PROMPT_V1.txt         (详解)
  PLAN_WRITER_INSTRUCTION_V1.txt    (Appendix B)
```

Full extraction logs + per-file sha256 in `work\current-change\word-imports\` (staging only).

## 4. Execution model

- Development execution model: `deepseek-v4-pro` (per user requirement; no model is actually billed during development — deterministic/local providers only).
- Site teaching/classification/problems/explanations: `qwen3.8-max` (per user requirement; REAL paid verification requires an explicit budget approval — otherwise recorded `NOT_RUN`).
- Embeddings remain independently configured; no vector re-embedding is triggered by this round.

## 5. Baseline code facts (to be refined by REQUIREMENTS_TRACEABILITY.md)

- Course ID generator appends timestamp: `ui_extension/domain.py:261-269 _new_course_id` → `slug-YYMMDDHHMMSS`.
- Dual-pane linkage lives in `cmui_layout` (owner+course → teach_conversation/problem_conversation/active_node); conversations are per-lane rows in `cmui_conversations`.
- Teaching runs: `cmui_runs` with statuses queued/planning/generating/completed/failed/cancelled; `cmui_run_events` SSE log; `generated_prompt` column exists (plan) — user-visibility to be audited and removed.
- Inbox/DM already exists: `cmui_threads`, `cmui_direct_messages` (idempotent request_id), `cmui_notifications`, `/people` directory endpoint.
- No existing: template registry, course classification, student verification, course snapshot sharing, teaching_mode field, answer-hiding for exercises, explanation windows.
- Local dev DB courses show `('official', 2), ('user', 3)` course_type values — new display types (校园课程/共享课程) must be mapped without re-keying access rules.
