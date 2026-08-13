# CourseMate V2 File Request Packs

Each pack contains the smallest practical set for a future ChatGPT teaching/review session. Upload
the listed files from the repository; paths are relative to the root. Some cross-cutting behavior
needs five files to preserve the contract, implementation and test evidence.

| Pack | Files |
|---|---|
| V2-01 Conversation | `app/models.py`, `app/api/qa.py`, `app/services/qa.py`, `ConversationSidebar.tsx`, `test_qa_api.py` |
| V2-02 Query Router | `app/tutor/routing.py`, `app/tutor/rewrite.py`, `app/tutor/strategy.py`, `test_tutor_routing.py`, `test_query_rewrite.py` |
| V2-03 Tutor Prompt | `app/rag/prompt.py`, `app/services/qa.py`, `app/tutor/strategy.py`, `test_tutor_prompt.py` |
| V2-04 Exact Locator | `app/tutor/references.py`, `app/rag/structure.py`, `app/rag/retrieval.py`, `test_reference_parser.py`, `test_real_course_golden.py` |
| V2-05 Retrieval | `app/rag/retrieval.py`, `app/repositories/chunks.py`, `app/services/qa.py`, `test_retrieval_evaluation.py` |
| V2-06 Provider | `app/config.py`, `app/rag/answers.py`, `app/rag/embeddings.py`, `agent-api/src/config.ts`, `MODEL_BENCHMARK_2026.md` |
| V2-07 Create Course | `app/course_access.py`, `app/services/ingestion.py`, `CourseCenterPage.tsx`, `CourseCenterPage.test.tsx` |
| V2-08 Upload/Ingestion | `app/api/ingestion.py`, `app/services/ingestion.py`, `app/rag/loaders.py`, `CourseSettingsPage.tsx`, `test_ingestion_api.py` |
| V2-09 Teaching Profile | `app/models.py`, `app/api/teaching_profiles.py`, `app/services/teaching_profiles.py`, `test_teaching_profiles_api.py` |
| V2-10 Prompt Builder | `app/services/teaching_profiles.py`, `CourseSettingsPage.tsx`, `ragApi.ts`, `ragApi.test.ts` |
| V2-11 Publication | `app/api/publication.py`, `app/services/publication.py`, `AdminPublicationPage.tsx`, `test_publication_api.py` |
| V2-12 Database | `app/db.py`, `005_007_v2_course_platform.sql`, `test_database.py`, `V2_DATABASE_MIGRATION.md` |
| V2-13 Tests | `tests/e2e/coursemate.spec.ts`, `V2_TEST_REPORT.md`, `playwright.config.ts` |
| V2-14 Production | `V2_PRODUCTION_DEPLOYMENT.md`, `backup_v2.sh`, `restore_v2.sh`, `.env.example`, `netlify.toml` |

For RAG paths, prefix `services/rag-api/`; frontend paths live under `apps/web/src/`; Agent paths
under `services/agent-api/`; operational scripts under `ops/`; documentation under `docs/`.
