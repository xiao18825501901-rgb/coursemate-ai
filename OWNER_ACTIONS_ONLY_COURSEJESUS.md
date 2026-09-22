# OWNER_ACTIONS_ONLY_COURSEJESUS

Only the actions that genuinely cannot be done from this machine with the access that already
exists. This is a fallback card set, not a list of things that are currently broken, and it is not
a request to log into every account. Everything else in the plan — source code, tests,
configuration, reading the two local Canvas roots, backups, migrations and controlled releases —
is executed by DSH.

**Key principle (unchanged):** passwords, codes, PATs, OAuth client secrets, SSH keys and platform
tokens are never posted in chat, never written into reports and never committed. They go into a
protected environment or the existing secret mechanism only.

## 1. Logo artwork

* **Goal:** replace the text-only brand with the owner's real asset.
* **Done already:** the brand scan found no logo files in the tree and found that
  `apps/web/public/manifest.json` does not exist, so the manifest and favicon have to be created.
* **Need from the owner:** the original file(s) (SVG or PNG), and a note on which one is primary
  plus whether there are light/dark variants.
* **Not needed:** resizing, favicon generation, SVG cleaning, manifest wiring — DSH does all of
  that, validates the real file and records the hashes.
* **Success looks like:** a validated asset in the tree with generated sizes and a clean SVG; until
  then the status stays `PENDING_ASSET` and image work does not block anything else.

## 2. Aliyun domain, real-name verification and ICP filing

* **Goal:** make `coursejesus.com` resolve to the same production site, and keep the old domain
  working during a compatibility window.
* **Done already:** the domain is confirmed to exist in the plan; **no DNS, zone, NS or hold-state
  read has been performed yet** — DSH does that read-only inventory first and only then reports
  which records it can change itself.
* **Need from the owner (only if the check requires it):** sign in to the Aliyun console →
  domain console → `coursejesus.com` → complete holder e-mail / real-name verification when
  prompted.
* **If the new public backend host points at a mainland ECS:** ICP filing is a real-name process
  that the owner must submit; DSH prepares the domain/instance/site description and does not work
  around the review. The old `qqttai.com` being reachable does **not** mean the new domain is
  filed.
* **Not needed:** transferring the registrar, clearing the zone, or deleting MX/TXT/other records.
* **Success looks like:** the new records exist in the *authoritative* zone and TLS validates; a
  "changed the registrar page" screenshot is not success.

## 3. GitHub repository rename

* **Goal:** the same repository under the name `coursejesus`, keeping id, history, issues, PRs,
  branches and visibility.
* **Done already:** `git remote -v` confirms `https://github.com/xiao18825501901-rgb/coursemate-ai.git`.
* **Need from the owner (only if DSH lacks repository admin):** repository → Settings → General →
  Repository name → `coursejesus` → Rename.
* **Not needed:** creating a new empty repository and copying code (that loses history), changing
  the account user name, or forcing the default branch name.
* **Success looks like:** rename done, then DSH updates the local remotes, CI references and the
  Netlify link, and verifies fetch/push and a build. If the target name is taken by another
  project, DSH reports the exact conflict instead of renaming someone else's repository.

## 4. Netlify and Clerk (only if MFA is required)

* **Goal:** keep the **same** Netlify site (same Site ID and deploy history) and the **same** Clerk
  Production instance and user identities, while changing the domain and display name.
* **Done already:** nothing inspected yet; DSH will do the read-only inventory first.
* **Need from the owner (only when MFA blocks it):** Netlify → the existing site → Domain
  management → Add a domain you already own; Clerk → the existing Production instance → Domains →
  Change domain.
* **Not needed:** a new Clerk application, copying the old publishable key to the new domain, or
  shutting the old site down before the new key/issuer/CORS are in place.
* **Success looks like:** the same Clerk user id signs in on the new domain and still sees the same
  courses, history, grades and files. A Clerk sign-in error is **not** covered by the homepage
  returning 200.

## 5. School Canvas administrator access (institution Developer Key)

* **Goal:** let students authorise their own Canvas account with OAuth instead of pasting a
  manually generated token.
* **Done already:** design frozen (per-institution client + fixed callback + one-time state);
  the application draft is `CANVAS_ADMIN_OAUTH_REQUEST.md`, and `CANVAS_ADMIN_OAUTH_REQUEST.md` in
  the pack is the letter to send, unmodified except for the real contact details.
* **Need from the owner:** submit that request to the school's Canvas/IT administrator for the
  correct instance (`https://canvas.cityu.edu.hk` and/or `https://cityu-dg.instructure.com`), and
  supply the approved client secret **only** through a protected configuration channel.
* **Not needed:** the owner's personal student token being used to mint an institution key — that
  is not possible, and DSH will not pretend it is; nor does the owner's consent replace each
  student's own consent on the school login page.
* **Success looks like:** the school enables a Developer Key with the read-only scope set in the
  draft letter; until then the public UI says "学校连接尚未开通" and offers local file upload, and
  the status stays `NOT_CONFIGURED` rather than being reported as done.

## 6. Publication rights for the campus review list

* **Goal:** decide what may be republished to every registered user of CourseJesus.
* **Done already:** the read-only scan produced the full list — 21 restricted and 13 training
  files, grouped in `docs/coursejesus/CAMPUS_SOURCE_AND_PUBLICATION_MATRIX.md` §5 into
  personal/administrative data (8), instructor answer sets (13) and mandatory-training material
  (13).
* **Need from the owner:** one decision per group, not per file. The 8 personal/administrative
  items (class lists, attendance, submissions, individual feedback) are recommended **not** to be
  published and need no action. The 13 answer sets and the 13 training items need a yes/no on
  whether they belong in the campus library.
* **Not needed:** manually moving 1919 files, or deciding file by file.
* **Success looks like:** each of the 40 files has a recorded decision and its
  `review_status`/`publication_basis` in the inventory reflects it; anything undecided stays
  unpublished.

## 7. Spend beyond the existing policy

* **Goal:** keep batch ingestion and generation inside an approved amount.
* **Done already:** the local scan and classification cost nothing, and no model was called. The
  historical USD 27 proposal from an earlier round is **not** an approved budget for this work, and
  neither is the website's maximum plan.
* **Need from the owner:** after DSH estimates tokens/embeddings for the chosen courses per batch,
  approve the total (or set a ceiling). Steps that cost nothing — scanning, deduplication, parsing,
  file upload, UI work — continue regardless.
* **Success looks like:** a single approved ceiling with a per-batch estimate, and generation jobs
  stopping at the ceiling instead of running open-ended.
