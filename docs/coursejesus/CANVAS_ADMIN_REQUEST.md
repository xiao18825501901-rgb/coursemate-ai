# CANVAS ADMIN REQUEST — CourseJesus read-only OAuth (task B2)

**State.** A prepared request, **not sent**. It is addressed to the school's Canvas administrator
for whichever instance applies; submitting it is an owner action (`OWNER_ACTIONS_ONLY_COURSEJESUS.md`
§5). Nothing here asserts that a school has approved anything.

---

**Subject: request to configure a read-only Canvas OAuth Developer Key for CourseJesus, a student
study-material tool**

Hello,

I would like to request official OAuth access to Canvas for a student study-material tool I am
developing, **CourseJesus** (Chinese name 耶课稣, `https://coursejesus.com`). The tool lets a student
authorise their own account on the school's Canvas page and then choose files from courses they can
already access, copying them into their own private study space. Students are **not** asked to
generate a personal access token and hand it to the site.

Canvas instances involved (whichever applies to your institution):

```text
CityU:      https://canvas.cityu.edu.hk
CityU (DG): https://cityu-dg.instructure.com
```

Application site: `https://coursejesus.com`

Proposed OAuth callback (will be frozen against the deployed backend route before submission; this
exact value is the only one registered, and a user-supplied address is never substituted):

```text
https://rag.coursejesus.com/api/integrations/canvas/oauth/callback
```

## Requested read-only capability

1. Read the authorising user's own basic profile, to confirm which account a connection belongs to.
2. Page through the courses in which that user has a **student** enrolment — both current and, where
   still readable, completed/historical ones.
3. After the student selects courses, read those courses' file metadata plus the folder/module
   relationships needed to place those files, and download files the student is still permitted to
   read.
4. Standard OAuth token refresh (`expires_in` is one hour in Canvas's documented response) and
   user-initiated revocation of the connection.

The endpoints involved, with the scope identifiers in Canvas's documented
`url:<VERB>|<path>` form — please confirm the exact strings your instance will grant (the
authoritative list is per-account, via `GET /api/v1/accounts/:account_id/scopes`):

```text
GET /api/v1/users/self/profile                     url:GET|/api/v1/users/self/profile
GET /api/v1/courses                                url:GET|/api/v1/courses
GET /api/v1/users/self/enrollments                 url:GET|/api/v1/users/self/enrollments
GET /api/v1/courses/:course_id/files               url:GET|/api/v1/courses/:course_id/files
GET /api/v1/courses/:course_id/files/:id           url:GET|/api/v1/courses/:course_id/files/:id
GET /api/v1/files/:id                              url:GET|/api/v1/files/:id
GET /api/v1/courses/:course_id/folders             only if folder relationships are needed
GET /api/v1/folders/:id/files                      only for folders of the selected course
GET /api/v1/courses/:course_id/modules             optional, for file relationships only
GET /api/v1/courses/:course_id/modules/:module_id/items
```

A narrower grant is entirely acceptable: if some optional endpoint is not permitted, the application
marks that part as unavailable and works with what remains, rather than working around it.

## Capability explicitly NOT requested

No uploading or submitting assignments, no answering quizzes, no changes to courses, grades or
enrolments, no access to other students' submissions or private messages, no teacher or
administrator privileges, no masquerading as another user, and no writing to any course.

## Data and security arrangements

* The student authorises through the school's own OAuth page; the application uses a one-time
  `state` bound to the signed-in CourseJesus account and to the institution, consumed on both
  success and failure.
* Access and refresh tokens are stored only in the backend's protected credential store, encrypted
  with a key id, never in chat, front-end readable storage, model requests or ordinary logs.
* Only the course set the student confirms is downloaded. The imported material is **private to that
  student** by default and does not become a published campus course as a side effect.
* The student can disconnect at any time; the connection is revoked through Canvas's documented
  `DELETE login/oauth2/token`, and deleting already-imported material is a separate explicit choice.
* Content the school has closed, locked or that returns `403` is recorded as inaccessible and never
  worked around.
* Later AI-based study features may process the material the student chose using our DeepSeek and
  TypeSafe components; this is disclosed in the product. **Canvas credentials are never given to a
  model.**
* Permission to redistribute course material publicly is handled separately from this access
  request; this request does not assume that downloading a file grants redistribution rights.

Please let me know the acceptable Developer Key configuration process, the minimum scope set, any
test requirements, and whether an additional security or privacy review is needed.

The applicant's name, student number, school e-mail and contact details are filled in by the
applicant in the school's own ticket/e-mail system and are deliberately not included in this
public repository.

Thank you.

---

## Verified protocol facts behind this request (round 44)

| Fact | Source |
|---|---|
| Scope identifier format `url:<VERB>\|<path>` | Instructure's *API Token Scopes* page |
| Per-account scope enumeration `GET /api/v1/accounts/:account_id/scopes` (documented BETA) | same |
| Authorisation `GET …/login/oauth2/auth?client_id&response_type=code&state&redirect_uri`; only `code` supported | Instructure's OAuth page |
| Callback receives `?code&state`; denial is `?error=access_denied&state` | same |
| Exchange/refresh `POST login/oauth2/token` with `grant_type`, `client_id`, `client_secret`, `redirect_uri`, `code`; response carries `access_token`, `refresh_token`, `expires_in` (**3600 s**) | Instructure's OAuth endpoints page |
| Revocation `DELETE login/oauth2/token` | same |
| PKCE parameters are **not** documented for this flow | same — hence no self-invented PKCE fields |

Full design: `docs/coursejesus/CANVAS_OAUTH_AND_SCOPES.md`.
