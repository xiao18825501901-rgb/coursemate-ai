# V2 Private User Courses

## Lifecycle

An authenticated ordinary user creates a `user` course that is `private` by default. An
administrator-created course is `official`, `public` and `published`. Owners can rename, describe,
upload to, query and delete their private courses. Administrators retain operational access.

```text
create -> private -> upload/index -> teach/profile -> submit for review
                    ^                                  |
                    `---- reject/unpublish <--- published
```

The course response reports `courseType`, `visibility`, `publicationStatus`, `isOwner` and
`canManage`; it excludes the raw owner ID. Course lists are paginated and contain only official/
community public rows plus the caller's own private rows (administrators can inspect all).

## Authorization matrix

| Operation | Owner, private | Other user, private | Other user, published | Administrator |
|---|---:|---:|---:|---:|
| List/read/query | yes | hidden | yes | yes |
| Update/delete | yes | hidden | no | yes |
| Upload/delete document | yes | hidden | no | yes |
| Teaching profile | yes | hidden | read only through tutoring | yes |
| Submit publication | yes | hidden | n/a | no owner substitution |

Published owners receive `409 PUBLISHED_COURSE_LOCKED` for mutations. An administrator must first
unpublish, after which the owner can edit and submit a fresh review.

## File ingestion

The multipart upload endpoint accepts PDF, Markdown, text, DOCX and PPTX up to
`MAX_UPLOAD_BYTES` (20 MiB by default). It generates document IDs and stored paths, hashes content,
rejects duplicate/unsupported/oversized files, records an ingestion job and builds isolated chunks
and embeddings. Job polling exposes only safe status/error metadata. Filesystem deletion resolves
the stored path under the configured upload root before removal.

## Delete behavior

Course deletion is owner/admin-only and is blocked for a published owner. The service removes
known stored files under the upload root and deletes the course; SQLite cascades documents, jobs,
chunks, FTS trigger rows, conversations/messages, profiles and publication records. This is an
explicit hard delete, so production backup is required before release and the UI asks for
confirmation.

## UI

`/courses` groups Official Courses, My Courses and Community Courses. `/courses/:courseId/settings`
provides file/index status, upload/delete, teaching-profile builder and publication consent. Private
creation/upload/chat/delete and mobile behavior are covered by component and Chrome tests.

## Remaining operational policy

The service enforces a per-file byte limit and per-user QA limits. Per-user total course/file/storage
quotas were planned but are not implemented in this release; production must therefore set disk
alerts and administrator policy before broad self-service rollout.
