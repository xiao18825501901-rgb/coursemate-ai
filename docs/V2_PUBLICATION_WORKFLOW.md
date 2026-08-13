# V2 Publication and Moderation Workflow

## State machine

```text
private/rejected -- owner dual consent --> pending
pending -- admin reject ----------------> rejected + private
pending -- admin approve ---------------> published + public + owner locked
published -- admin unpublish -----------> private + editable
```

There is no direct owner “make public” operation. Submission requires both
`shareMaterialsConsent=true` and `rightsConfirmation=true`, plus a versioned consent label. The
server records owner, consent time, submission time and immutable request ID. A single active pending
request is allowed per course.

Only a configured administrator can list pending requests and approve/reject them. Review records
store reviewer, timestamp and note, while API serialization excludes raw owner/reviewer IDs.
Approval atomically sets course visibility/publication timestamps; rejection remains private.

## Post-review integrity

Community users can list, read and query approved courses but cannot update, upload or delete. The
owner is also prevented from changing reviewed content, files or teaching profiles and receives
`PUBLISHED_COURSE_LOCKED`. This closes the post-approval replacement gap. An administrator can
unpublish before an owner edits and resubmits.

## Interfaces

```text
POST   /api/courses/{courseId}/publication-requests
GET    /api/admin/publication-requests
POST   /api/admin/publication-requests/{requestId}/review
DELETE /api/admin/courses/{courseId}/publication
```

The owner settings UI presents the two consent checkboxes and current state. The admin review page is
available at `/admin/publications`; server authorization remains decisive even if a user navigates
directly to the route.

## Audit limitations

Audit rows are durable in the application database but are not an external append-only compliance
ledger. Course deletion cascades them. Organizations requiring legal-grade retention must export
publication records to immutable storage before enabling deletion.
