# CourseMate V2 File Request Packs

Each pack contains the smallest practical set for a future ChatGPT teaching/review session. Upload
the listed files from the repository; paths are relative to the root. Some cross-cutting behavior
needs five files to preserve the contract, implementation and test evidence.

| Pack | Files |
|---|---|
| V2-01 Conversation | `services/rag-api/app/models.py`, `services/rag-api/app/api/qa.py`, `services/rag-api/app/services/qa.py`, `apps/web/src/components/ConversationSidebar.tsx`, `services/rag-api/tests/test_qa_api.py` |
| V2-02 Query Router | `services/rag-api/app/tutor/routing.py`, `services/rag-api/app/tutor/rewrite.py`, `services/rag-api/app/tutor/strategy.py`, `services/rag-api/tests/test_tutor_routing.py`, `services/rag-api/tests/test_query_rewrite.py` |
| V2-03 Tutor Prompt | `services/rag-api/app/rag/prompt.py`, `services/rag-api/app/services/qa.py`, `services/rag-api/app/tutor/strategy.py`, `services/rag-api/tests/test_tutor_prompt.py` |
| V2-04 Exact Locator | `services/rag-api/app/tutor/references.py`, `services/rag-api/app/rag/structure.py`, `services/rag-api/app/rag/retrieval.py`, `services/rag-api/tests/test_reference_parser.py`, `services/rag-api/tests/test_real_course_golden.py` |
| V2-05 Retrieval | `services/rag-api/app/rag/retrieval.py`, `services/rag-api/app/repositories/chunks.py`, `services/rag-api/app/services/qa.py`, `services/rag-api/tests/test_retrieval_evaluation.py` |
| V2-06 Provider | `services/rag-api/app/config.py`, `services/rag-api/app/rag/answers.py`, `services/rag-api/app/rag/embeddings.py`, `services/agent-api/src/config.ts`, `docs/MODEL_BENCHMARK_2026.md` |
| V2-07 Create Course | `services/rag-api/app/course_access.py`, `services/rag-api/app/services/ingestion.py`, `apps/web/src/pages/CourseCenterPage.tsx`, `apps/web/src/pages/CourseCenterPage.test.tsx` |
| V2-08 Upload/Ingestion | `services/rag-api/app/api/ingestion.py`, `services/rag-api/app/services/ingestion.py`, `services/rag-api/app/rag/loaders.py`, `apps/web/src/pages/CourseSettingsPage.tsx`, `services/rag-api/tests/test_ingestion_api.py` |
| V2-09 Teaching Profile | `services/rag-api/app/models.py`, `services/rag-api/app/api/teaching_profiles.py`, `services/rag-api/app/services/teaching_profiles.py`, `services/rag-api/tests/test_teaching_profiles_api.py` |
| V2-10 Prompt Builder | `services/rag-api/app/services/teaching_profiles.py`, `apps/web/src/pages/CourseSettingsPage.tsx`, `apps/web/src/services/ragApi.ts`, `apps/web/src/services/ragApi.test.ts` |
| V2-11 Publication | `services/rag-api/app/api/publication.py`, `services/rag-api/app/services/publication.py`, `apps/web/src/pages/AdminPublicationPage.tsx`, `services/rag-api/tests/test_publication_api.py` |
| V2-12 Database | `services/rag-api/app/db.py`, `services/rag-api/migrations/005_007_v2_course_platform.sql`, `services/rag-api/tests/test_database.py`, `docs/V2_DATABASE_MIGRATION.md`, `ops/backup_v2.py` |
| V2-13 Tests | `tests/e2e/coursemate.spec.ts`, `docs/V2_TEST_REPORT.md`, `playwright.config.ts` |
| V2-14 Production | `docs/V2_PRODUCTION_DEPLOYMENT.md`, `ops/backup_v2.py`, `ops/restore_v2.py`, `ops/monitor_v2.py`, `netlify.toml` |

Every entry is a repository-relative path and every pack contains one to five files. The list is
covered by an automated existence/cardinality test so renamed or missing files fail the local gate.
