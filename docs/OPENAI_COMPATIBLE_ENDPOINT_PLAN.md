# Implementation Plan: OpenAI-Compatible Model Endpoints

## Architecture Decisions

- Keep provider mode named `openai`; `OPENAI_BASE_URL` only configures the official SDK transport endpoint.
- Treat the base URL as trusted deployment configuration, never as request input or an open proxy target.
- Preserve injected SDK clients so unit tests and downstream callers remain compatible.
- Use a named ingestion batch constant of 10 to match the target embedding API limit.

## Task List

### Phase 1: Contract tests

- [ ] Add RAG Settings/provider wiring tests and a greater-than-10-chunk ingestion test.
- [ ] Add Agent config, custom SDK base URL, and injected-client tests.

Verification: focused Pytest and Vitest runs fail before implementation and pass afterward.

### Phase 2: Backend compatibility

- [ ] Add optional RAG `openai_base_url`, pass it through application composition, and conditionally configure both SDK clients.
- [ ] Change ingestion embedding batches from 64 to the named limit 10.
- [ ] Add optional Agent `openaiBaseUrl`, conditionally configure the SDK, and pass it from server composition.

Verification: RAG/Agent focused tests plus existing Function Calling tests pass.

### Phase 3: Production configuration and documentation

- [ ] Document unset/empty versus custom endpoint behavior and safe secret handling.
- [ ] Configure the Render Blueprint with the non-secret Singapore endpoint and target model names.
- [ ] Record official Alibaba Cloud compatibility references.

Verification: inspect the staged diff and scan tracked content for assigned credentials.

### Phase 4: Release gates

- [ ] Run all RAG, Agent, and Web tests; Ruff; mypy; TypeScript typecheck; and both builds.
- [ ] Review scope, backward compatibility, security boundaries, and rollback.
- [ ] Commit the cohesive feature and push only if branch, authentication, tests, and clean-tree conditions all hold.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Empty endpoint overrides the SDK default | High | Add explicit empty/unset tests and only pass truthy values. |
| Embedding API rejects oversized batches | High | Named limit of 10 plus a 12-chunk exact-count test. |
| Constructor change breaks mocks | Medium | Keep the injected client as the second parameter and test it. |
| Provider adaptation changes tool behavior | High | Do not rewrite the loop; run all Function Calling tests. |
| Secret leaks into Git | High | Use placeholders only and scan the final diff/tracked files. |

## Open Questions

None.
