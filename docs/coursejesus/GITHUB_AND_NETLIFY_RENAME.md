# GITHUB, NETLIFY AND CLERK RENAME / REBIND (task A2)

**State of this document.** Round-46 record of what is verified about the repository and the
hosting, what the rename requires, and what is owner-blocked. **Nothing has been renamed or
rebound**: no GitHub setting, Netlify setting or Clerk setting has been touched.

## 1. Verified facts (not inferred from old reports)

| Fact | Value | How it was verified |
|---|---|---|
| Git remote | `https://github.com/xiao18825501901-rgb/coursemate-ai.git` (fetch and push) | `git remote -v` in the work tree |
| Default production front end | `https://qqttai.com` answers **200** | public HTTP HEAD from this machine |
| `www` behaviour | `https://www.qqttai.com` → **301** → `https://qqttai.com/` | same |
| Netlify site | `www.qqttai.com` is a CNAME to **`coursemate-ai-qqtt.netlify.app`** | DNS query, round 44 |
| Netlify default domain | `https://coursemate-ai-qqtt.netlify.app` answers **200** | public HTTP GET |
| API hosts | `rag.qqttai.com` and `agent.qqttai.com` → `47.114.34.175` (both names, one host) | DNS query, round 44 |
| Target repository name | `coursejesus`, same owner, same repository | the pack's requirement |
| Target site name | same Netlify **site**, display name updated; the site's default subdomain keeps working | the pack's requirement |

The Netlify site's default subdomain still carries the old product name (`coursemate-ai-qqtt`). That
is a *site name*, not a repository name: the pack allows changing the display/site name while
keeping the Site ID and deploy history, and it requires the old `netlify.app` link to keep working.
Nothing here says the subdomain can or cannot change — that is a Netlify-console question, and it is
listed as an owner item rather than assumed.

## 2. Why the repository rename is not just a string change

Renaming the repository changes the canonical clone URL and the URLs GitHub uses for its own
features. The pack lists the specific traps, and each is checked here as a *step*, not a promise:

| Step | Why |
|---|---|
| Record the current repository identity first (owner, name, default branch, visibility, last commit SHA) | so the rename can be shown to have preserved history rather than recreated it |
| Check what reacts to a push before renaming | a GitHub App, a CI workflow or a deploy hook that publishes on push must not fire a half-configured production build during the change |
| Rename in place (`Settings → General → Repository name`) | renaming preserves the repository id, commits, issues, PRs, branches and visibility; creating a new repository and copying code loses all of that |
| Update every local clone/remote, and any workflow that hard-codes `owner/repo` | Git's HTTP redirect for the *git* endpoints is a convenience, **not** a guarantee for Actions or other API consumers |
| Verify by fetching and pushing from the work tree afterwards | "the redirect probably covers it" is exactly the assumption the pack warns about |

Local work tree: `origin` is the only remote, and the branch is `fix/codex-dsh-audit-20260919`
with 80+ commits that have never been pushed. That matters: the rename must not be the moment the
first push happens, or an untested branch would land in a renamed repository.

## 3. Order of operations (planned, not executed)

1. Freeze the current state: all local work committed, the full gate green on one revision, and the
   exact SHAs recorded.
2. Read-only inventory of the platform settings (repository settings and any App/CI integration,
   Netlify site settings and the current production deploy, Clerk instance and domain settings).
3. Decide and record how automatic deploys are held back for the duration of the change.
4. Rename the repository (owner action if the tooling lacks admin).
5. Update the local remote and verify fetch/push; then update any explicit `owner/repo` reference
   and the Netlify link if the site is configured by repository.
6. Only then continue with the domain/Clerk work in `DOMAIN_AND_CLERK_MIGRATION.md`, which is the
   part that can interrupt logins and therefore needs the maintenance window.

## 4. Owner actions (only if the tooling lacks the access)

* Repository rename: repository → Settings → General → Repository name → `coursejesus` → Rename.
* Netlify display/site name: site configuration → change site name (keep the Site ID).
* Either platform's MFA, and the Clerk console work.

Everything else — inventory, the remote/CI updates, the verification fetches and pushes, and the
rebuild — is technical work that does not need the owner. See
`OWNER_ACTIONS_ONLY_COURSEJESUS.md` §3 and §4.

## 5. Honest limits

* No platform console has been read yet: the Site ID, the deploy history, any GitHub App/CI
  integration, and the Clerk instance settings are all unverified at this point. §2's steps are a
  plan derived from the pack and from public behaviour, not from account state.
* The rename has **not** happened, so `REPOSITORY_RENAME` remains `NOT_STARTED`.
* The old domain's compatibility window (30 days) is a decision recorded in the migration
  document, not something configured today.
