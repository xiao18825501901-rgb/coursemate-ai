# TEMPLATE_REGISTRY_AND_CLASSIFICATION

## Registry

- Runtime resources: `services/rag-api/app/cm_update/prompts/`
  - `01_…V1.txt` … `14_…V1.txt` — the 14 professional templates, full extracted bodies
    between each Word document's own 【可复制 Prompt 开始】…【可复制 Prompt 结束】 markers
    (sections 5–10 included, `ciallo` rules, per-profession emphasis preserved).
  - `15_OTHER_GENERAL_V1.txt` — Appendix A OTHER template (cross-disciplinary).
  - `EXERCISE_PROMPT_V1.txt` (做一题), `PROBLEM_PROMPT_V1.txt` (题目),
    `EXPLANATION_PROMPT_V1.txt` (详解) — extracted from the owner's Word files
    (【完整 Prompt 开始】…【完整 Prompt 结束】).
  - `PLAN_WRITER_INSTRUCTION_V1.txt` — Appendix B internal plan-writer role.
  - `CLASSIFICATION_INSTRUCTION_V1.txt` — classifier instruction (JSON-only output).
  - `cs3481_original.txt` / `CS3481_ORIGINAL_TEMPLATE_V1.txt` — original CS3481.doc full text (history).
- Loader: `app/cm_update/templates.py` (`registry()`, `template_body()`, `registry_json()`).
- Audit: each entry records version, level, professional name, file sha256, body sha256.
  Body hashes (V1, sha256[:12]): 01 `e73746849d` · 02 `6155e91575` · 03 `1ee0c518d4` ·
  04 `6de17fcf73` · 05 `4734f8afee` · 06 `142bd78222` · 07 `a8e133c7a7` · 08 `08345ab1ed` ·
  09 `f8f770c617` · 10 `5e972ae981` · 11 `1f292bb895` · 12 `c5aea12f6d` · 13 `e03bb9da91` ·
  14 `7f098a19c9` · OTHER `da1dcd8414`.
- Source Word files were read-only imports from
  `C:\Users\Hp\xwechat_files\wxid_lpdn28neu0i112_ecd6\msg\file\2026-09`; the originals were
  never modified. Import staging (full text + hashes) is in `work/current-change/word-imports/`.

## Classification

- State machine: `WAITING_FOR_MATERIALS → CLASSIFYING → CLASSIFIED | OTHER | FAILED_RETRYABLE`
  (`cmui_classifications` table, one row per course).
- Trigger: a successful course-material upload schedules one background
  classification (deduplicated per course; materials revision = sha256 over file ids+hashes
  so re-runs only happen when the material set changes).
- Input bundle: course name/code/description, up to 40 file names/sizes, bounded text
  samples (standalone chunk text; integrated mode uses file metadata only), materials_revision.
  Never includes other users' files.
- Validation (`social.validate_classification`): template_id must be in the registry;
  confidence below 0.6, ambiguous or missing evidence → OTHER with a recorded reason;
  alternatives kept. Model confidence is treated as uncalibrated.
- Manual correction: `POST /courses/{cid}/classification {template_id}` (owner or admin),
  stored with `source='manual'`; automatic jobs never overwrite manual rows.
- Thinking-mode template resolution: classification `template_id` when `CLASSIFIED`,
  otherwise `OTHER` (temporary fallback, never blocks teaching).
- Real-model classification: NOT_RUN (no billable approval). The deterministic test
  provider classifies data-science-flavoured courses to `03` for local verification.
