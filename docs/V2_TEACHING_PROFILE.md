# V2 Teaching Profile and Prompt Builder

## Contract

Every course may have immutable, monotonically versioned teaching profiles. A profile contains
language, student level, learning goal, teaching styles, answer depth, example/exercise policy,
exam orientation, citation preference, math detail, terminology style and bounded custom notes.
Strict Pydantic enums/lengths reject unknown or malformed fields.

```text
POST /api/teaching-profiles/preview
GET  /api/courses/{courseId}/teaching-profiles
POST /api/courses/{courseId}/teaching-profiles
POST /api/courses/{courseId}/teaching-profiles/{version}/restore
```

The preview endpoint deterministically converts a short preference into a typed draft and generated
prompt without contacting a billable model. The web client deliberately posts only writable profile
fields; response-only `generatedPrompt` is never echoed into the strict save schema.

## Version pinning

Saving creates the next course version; prior versions are retained. On the first tutored turn, a
conversation pins the latest profile version in `conversations.teaching_profile_version`. Later
profile edits affect new conversations but do not silently change an existing learning session.
Restoring a historical version copies its validated fields into a new monotonically increasing
version; it never overwrites or deletes the audit history.

## Prompt hierarchy

The generated profile begins by declaring itself a teaching preference, not authorization or a
security rule. It is composed below fixed platform, grounding and citation instructions and above
untrusted course/history/user content. A custom requirement such as “ignore previous instructions”
is preserved only as low-trust text and cannot remove the surrounding rules.

## Ownership and publication

Only a private-course owner or administrator can save profiles; a foreign private course remains a
404. Once a course is published, owner profile changes are locked because they would alter reviewed
teaching behavior. Administrator unpublish restores owner editing.

## UI flow

The course settings page accepts a natural-language requirement, previews the typed result, allows
manual field adjustment and saves a new version. It displays the generated instruction and version
history. Loading, validation, API error and success states are explicit.
