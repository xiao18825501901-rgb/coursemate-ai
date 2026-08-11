# ADR-002: Use the Node runtime's SQLite API for Agent persistence

## Status

Accepted with a pinned runtime

## Date

2026-08-11

## Context

The Agent needs synchronous, server-owned SQLite with prepared statements, foreign keys, a busy timeout, WAL, and change counts. The original better-sqlite3 dependency added a native addon installation chain. On the verified Windows environment its Node 24 binary download was unreliable and compilation required MSBuild access outside the project sandbox. That made a clean lockfile install non-reproducible even though application behavior was correct.

Node 24.14 provides DatabaseSync in node:sqlite with every API this repository uses. It requires no package download, postinstall script, compiler, or platform-specific binary.

## Decision

Use node:sqlite DatabaseSync in the Agent database and repository. Pin the project and Agent engine to Node 24.14 or newer, keep prepared statements and the existing SQL schema, enable foreign keys and a 10-second timeout through constructor options, and enable WAL for file-backed databases.

## Consequences

- Clean npm ci is platform-independent and has no native addon build.
- One production dependency and its type package are removed.
- Repository code remains synchronous and its public contracts do not change.
- Node 24 reports node:sqlite as experimental. The runtime is pinned and all repository/API/tool behavior is covered by automated tests; upgrade to a release where the module reaches stable status when an LTS release provides it, then rerun the full gate.
- Deployments must not silently use Node 22 or an older Node 24 patch.

## Alternatives considered

- Keep better-sqlite3: mature API, but clean installation depended on a GitHub prebuild or local compiler and was not reproducible in the target environment.
- Use a WASM SQLite package: avoids native compilation but requires whole-file serialization and changes persistence semantics.
- Use an external PostgreSQL service: valid future adapter, but removes the requested local SQLite learning path and increases operating cost.
