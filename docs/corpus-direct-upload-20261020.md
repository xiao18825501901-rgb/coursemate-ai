# Corpus upload integration (2026-10-20)

The mounted UI used multipart uploads despite the existing OSS direct-upload host.
The two real UI upload callers now use the same signed PUT transport as the existing
RAG client. Authenticated begin/complete routes map UI course identity to the caller's
private workspace; ownership and course binding are checked again on completion.
This does **not** publish private files or change their source scope.

Existing storage sessions, canonical SHA verification, parser/indexer, upload batches,
course authority, retention and permissions remain authoritative. No schema migration.
Only signed OSS headers go to storage, never Clerk credentials. An uncertain PUT is
not automatically resent; the same selected File retries confirmation of its session.
An explicit LOCAL fallback retains multipart uploads without double-counting its
upload limit. Duplicate content returns the authorized existing document.

Parsing is serialized for this UI path in the supported single-worker host, off the
ASGI event loop. Pending/capacity-waiting documents remain recoverable, are not counted
as indexed, and retain their document/session identity. No unknown model request is
replayed. A page reload does not persist the in-memory transport session; operators
must reconcile existing storage sessions instead of treating the reload as success.

Curated open-source administration may set the internal `open_resource` creation
option. It reuses the existing canonical course host and shared-resource presentation,
not a school affiliation. Students cannot provide this option through CourseCreate.
The importer must independently bind the actual source, author, licence, version and
hash. This label is not evidence of a licence and does not make any private file public.

Validation at this checkpoint:

- 18 backend direct-storage, mounted-UI, lifecycle and OpenAPI tests passed before review.
- 12 related backend tests passed after the review fixes and open-resource option.
- 9 frontend upload/batch/dashboard tests passed; TypeScript passed.
- Independent review found and fixed LOCAL double rate counting, missing pending retry,
  and duplicate-file regression. Actual production/browser rollout still required.

Rollout: preserve latest live backend and Netlify identities; obtain the shared publish
lock; verify capacity, persistent backup and isolated startup; switch only the reviewed
modules and OSS configuration. Build with real production VITE/Clerk configuration.
Code rollback must retain OSS read capability and new student documents; never restore
an older database over new data. Do not publish the new frontend before backend routes.

The 200 GB counter includes only unique lawful originals actually imported, indexed
and published, with verified OSS content. Private test uploads and backups count zero.
