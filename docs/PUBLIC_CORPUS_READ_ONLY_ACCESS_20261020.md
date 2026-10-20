# Public corpus reads do not enroll the student

Observed production baseline: `63ede5a90da88ffaffc79b48611411a29db700e8`,
Schema 85. A real Clerk student at the existing 10-workspace cap received
`WORKSPACE_QUOTA` while listing an otherwise published Open Logic course.
The list projection called the enrollment helper before reading documents.

The file projection now checks course access and reads only an existing,
caller-owned workspace. It preserves official/private version predicates.
It does not create courses or workspaces, raise limits, clear counters, change
authentication, or modify learning/upload enrollment. File downloads reuse
this projection and retain document-version authorization.

Verification:

- RED: a file-list GET increased workspaces from 0 to 1.
- GREEN: integration and workspace suites, 20 passed.
- Added exact production-boundary test, 1 passed: 10 existing workspaces;
  explicit join still rejected; file list and original GET succeed; bytes
  match; no workspace added.
- Independent read-only review found no remaining blocker after the boundary
  test was added.
- Existing Starlette/httpx deprecation warning retained, not suppressed.

Deployment is a backend-only candidate. No schema or frontend change.
Code rollback must retain current databases, OSS configuration and newly
imported originals. Local test success is not a production acceptance receipt.
