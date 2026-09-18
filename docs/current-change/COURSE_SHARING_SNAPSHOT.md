# COURSE_SHARING_SNAPSHOT

## Freeze at send time

`POST /shares {course, recipients, history_scope: all|none|selected, selected_pair_ids,
request_id}` (idempotent by `(sender, request_id)`):

- `snapshot_at` + `source_course_version` recorded; file bytes are COPIED into
  `data/shares/{share_id}/` (immutable container) and indexed in `cmui_share_files`
  (name/size/mime/sha256/archived path). Sender-side later uploads cannot change the snapshot.
- History payload frozen via `social.snapshot_pair_payload` — visible messages only
  (both lanes, citations, reveal-visible state): NO runs, NO plan text, NO usage,
  NO third-party chats, NO cross-course material.
- Manifest (files + course meta + pairs + requires_student_verification) stored as JSON;
  share becomes `ready` only after file copies succeed — otherwise `failed`
  (never "looks complete" while incomplete).
- Recipients get inbox notifications; the inbox lists shares with sender, course name,
  snapshot time, file count and history scope.

## Join (receiver side)

`POST /shares/{id}/join` (idempotent per share+recipient):

- Campus-origin snapshots carry `requires_student_verification=true`; unverified
  recipients are blocked with the verification hint. The "共享课程" display label never
  replaces the access requirement.
- Standalone mode: `social.join_share` creates the recipient's own `cmui_courses` row
  (display_type='shared'), copies snapshot bytes into their uploads, remaps frozen pairs
  into recipient-owned pairs; every copied message carries
  `provenance='share:<share_id>'`; runs/usage/plans are never copied; LEARNED/grades/
  verification are never inherited.
- Integrated mode: a real V3 course is created via domain op `course.create_shared`
  (owner = recipient, display_type='shared', requires_student_verification preserved);
  history remap happens in the UI database the same way.
- The shared course does NOT appear in 所有课程/控制面板 until joined; joining is
  idempotent; different shares produce distinct snapshots (distinguished by send time,
  never by mangling the display name).

## Anti-leak guarantees

- Sender deletes/updates the source course → snapshots stay fixed (content-addressed
  copies; no live links).
- Share responses and the inbox DTOs never include plans, verification codes, provider
  secrets, or other users' private data.

## Scope notes (declared)

- File-snapshot copying is fully implemented in standalone mode; in integrated mode the
  V3 document/workspace remapping of file BYTES is limited to the share manifest +
  course creation (document-level deep copy for V3 workspaces is declared NOT_RUN for
  production and requires the deployment round).
