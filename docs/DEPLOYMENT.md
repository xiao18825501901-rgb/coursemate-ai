# Deployment: Netlify + Render

## Chosen topology

- Netlify: apps/web static Vite build.
- Render web service coursemate-rag-api: FastAPI plus a private persistent disk mounted at /var/data.
- Render web service coursemate-agent-api: Express plus a separate private persistent disk mounted at /var/data.

The root netlify.toml and render.yaml are ready for this topology. Render Starter plans are intentional: persistent disks are unavailable to free services, and SQLite would be erased on redeploy without a disk. A disk-mounted service cannot scale horizontally; keep each SQLite service at one instance.

## Pre-deploy gates

1. Confirm you are authorized to upload or publicly expose the course documents. Do not push data/uploads or data/rag.sqlite3 to a public repository without that permission.
2. Put the code in a Git repository accessible to Render and Netlify. Keep .env and private course data ignored.
3. Have an OpenAI API key with access to the configured chat and embedding models.
4. Have Render billing enabled for two Starter web services and two 1 GiB disks.
5. Authenticate Netlify CLI or connect the Git repository through the dashboard.
6. Create a Clerk application. Record its public publishable key and backend secret key in the platform secret stores; never paste them into documentation or Git.
7. In Clerk, authorize the final Netlify origin. Record the project owner's Clerk user ID for `ADMIN_USER_IDS`.

## Render backends

1. In Render, create a Blueprint from this repository. Render reads render.yaml.
2. Review both paid Starter services and disk charges before applying.
3. Enter `OPENAI_API_KEY` for both services when prompted.
4. Enter `CLERK_SECRET_KEY` for both services and `CLERK_PUBLISHABLE_KEY` for Agent. Optionally set `CLERK_JWT_KEY` on both for networkless verification. Set the RAG-only `ADMIN_USER_IDS` allowlist.
5. Temporarily set `WEB_ORIGIN` on both services to the anticipated Netlify URL or a controlled placeholder. Update it to the exact production origin after Netlify supplies the final URL.
6. Apply the Blueprint and wait for both health checks to pass. Both services fail closed if Clerk verification configuration is absent.
7. Record the public origins, for example https://coursemate-rag-api.onrender.com and https://coursemate-agent-api.onrender.com.
8. Verify:

       curl https://<rag-host>/health
       curl https://<agent-host>/health

The RAG disk stores rag.sqlite3 and uploads. The Agent disk stores agent.sqlite3. Only /var/data persists; never change the deployment paths to the service source directory.

## Initialize production course data

The Blueprint intentionally starts with an empty RAG database. After written authorization for the materials:

1. Sign in as the allowlisted administrator and obtain the session token through the normal Clerk client flow.
2. POST the two course records to `/api/courses` with the Bearer token.
3. Upload supported documents through the admin-authenticated upload API. The public UI intentionally has no corpus mutation controls.
3. Poll each ingestion job to completed.
4. Handle scanned PDFs with an authorized OCR workflow; the local source-specific sidecar is not sent automatically.
5. Run the five acceptance questions in docs/RAG_PIPELINE.md and inspect course isolation/citations.

Bulk copying a local SQLite file is possible only through a controlled disk-transfer procedure while the service is stopped. API reingestion is the safer auditable default.

## Netlify frontend

With Netlify CLI authenticated, from the repository root:

    npx netlify deploy

Choose Create & configure a new project when first prompted. The CLI reads netlify.toml and produces a draft URL. In Netlify site configuration, set build-scope environment variables:

    VITE_RAG_API_URL=https://<rag-host>
    VITE_AGENT_API_URL=https://<agent-host>
    VITE_CLERK_PUBLISHABLE_KEY=<Clerk publishable key>

Then create a production deployment:

    npx netlify deploy --prod

VITE variables are embedded into the browser bundle and therefore may contain only public API origins and the Clerk publishable key, never `CLERK_SECRET_KEY`, `CLERK_JWT_KEY`, or `OPENAI_API_KEY`. The SPA redirect in netlify.toml returns index.html for client routes.

## Close the CORS loop

After Netlify returns the production URL:

1. Set WEB_ORIGIN on both Render services to that exact origin, without a trailing slash.
2. Redeploy/restart both services.
3. Reload the Netlify site and verify course/task API calls have no CORS errors.

## Production acceptance

Run in a real browser:

1. Home and About load signed out; private navigation is absent. Sign up, sign in, profile, and sign out work.
2. Directly opening `/qa` or `/tasks` signed out shows the sign-in gate.
3. Sign in, select CS3481, and ask the DBSCAN question; see a streamed answer and CS citation.
3. Switch to GE2324 and ask the K-means assignment question; see a GE citation only.
4. Add the answer to the plan.
5. Ask the Agent to create a dated high-priority task.
6. Edit its date and priority, mark it complete, refresh, and verify persistence.
7. As an ordinary user, verify corpus upload API returns 403. As the allowlisted administrator, upload a small authorized TXT file and observe its job reach completed.
8. With two accounts, verify tasks and conversation history are mutually invisible and cross-owner mutation returns 404.
8. Redeploy each backend without deleting the disk and verify documents/tasks remain.
9. Check both health endpoints and browser console/network panel.
10. Confirm no secret appears in the built JavaScript, repository, logs, or error responses.

## Rollback

- Frontend: publish the previous successful Netlify deploy.
- Backend code: roll back the Git commit and redeploy; do not delete disks.
- Data: stop the owning service and restore the corresponding SQLite backup plus RAG uploads. Never restore one database over the other.
- If a migration becomes destructive, take a disk snapshot/copy first and document the forward and reverse transformations.

## Security controls and limits

- Both APIs independently verify Clerk session tokens and derive the user ID only from verified claims.
- `WEB_ORIGIN` is the sole allowed cross-origin browser origin; `Authorization` is explicitly allowed.
- Agent chat and RAG QA use SQLite-backed, per-user minute windows. Defaults are 10 requests/minute and can be tuned with `AGENT_CHAT_REQUESTS_PER_MINUTE` and `RAG_QA_REQUESTS_PER_MINUTE`.
- Shared course reads are authenticated. Course creation, upload, and ingestion-job inspection are admin-only through `ADMIN_USER_IDS`.
- SQLite requires one Render instance per service. Rate limits are intentionally single-instance and are not a substitute for Clerk signup controls, monitoring, budget alerts, or a future distributed gateway.

## Manual action required

Actual public deployment cannot be completed non-interactively unless the operator is authenticated to Clerk/Netlify/Render/GitHub, approves paid persistent disks, supplies secrets through platform UIs, connects a Git repository, configures the administrator allowlist and allowed origins, and authorizes publication/upload of the private course material. Those are security, billing, identity, and data-rights actions rather than missing code.
