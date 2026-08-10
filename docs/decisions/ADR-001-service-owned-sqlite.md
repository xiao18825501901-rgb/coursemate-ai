# ADR-001: Use service-owned SQLite databases locally

## Status

Accepted

## Date

2026-08-11

## Context

The required architecture has a Python RAG service and a Node.js task Agent. Both need genuine SQLite persistence, but their schemas, migrations, access patterns, and failure domains are independent. Letting both runtimes write one file would couple releases and increase lock-contention and schema-ownership ambiguity.

## Decision

Use `data/rag.sqlite3` for RAG state and `data/agent.sqlite3` for task/agent state. Each service initializes and migrates only its own database. A lowercase string `course_id` is the stable cross-service key. The QA-to-plan feature calls the Agent HTTP API instead of writing the task database from Python or React.

## Alternatives considered

### One shared SQLite file

- Pro: one file to inspect and back up.
- Con: two migration owners, cross-runtime locks, accidental table access, and tighter deployment coupling.
- Rejected because the small operational convenience does not justify unclear ownership.

### PostgreSQL for all environments

- Pro: stronger production concurrency and one managed database.
- Con: violates the learning requirement that local SQLite play a real role and increases setup cost.
- Rejected for the local version. A production adapter remains possible if a provider cannot supply persistent SQLite storage.

### Browser-side persistence

- Pro: simple demo deployment.
- Con: not server-authoritative, cannot support the required tool executor, and would make the database decorative.
- Rejected.

## Consequences

- Each service is independently testable and deployable.
- Cross-service actions are explicit HTTP contracts and cannot be atomic across both databases; the current handoff only writes Agent state, so no distributed transaction is needed.
- Backup and deployment documentation must cover two database files.
- Production hosting must provide persistent storage to both services or a documented adapter that preserves the local SQLite implementation.
