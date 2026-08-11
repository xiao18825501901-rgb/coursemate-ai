# Troubleshooting

## Start with evidence

Check the two health endpoints, browser network response, and service terminal before changing code. Reproduce in deterministic provider mode to separate product logic from credentials/network/model availability.

## Node or Vite refuses to start

Symptom: engine error, unsupported syntax, or Vite startup failure.

Cause: the global Node 18 runtime is older than this workspace's requirement. Use Node 24.14 or newer. Run node --version in the same shell that runs npm; npm lifecycle scripts must resolve the same runtime because the Agent uses node:sqlite.

## OPENAI_NOT_CONFIGURED

The .env file is missing, the key is empty, or the service did not load the expected working directory. Copy .env.example, set OPENAI_API_KEY without quotes/newlines, restart both APIs, and never print the key. Direct task CRUD still works. To prove the rest of the stack, set both provider modes to deterministic.

## OpenAI timeout or connection reset

If deterministic mode passes but live mode times out before an HTTP response, inspect firewall, proxy, TLS interception, DNS, and outbound allow-listing. Do not rotate or expose the key until network reachability is confirmed. A transport failure does not validate whether the model name or key is accepted.

## CORS error in the browser

WEB_ORIGIN must be the exact frontend origin, including scheme and port locally and with no trailing slash in production. Restart/redeploy both APIs after changing it. VITE_RAG_API_URL and VITE_AGENT_API_URL are frontend build variables, so rebuild/redeploy Netlify after changing them.

## Upload rejected

- FILE_TOO_LARGE: increase MAX_UPLOAD_BYTES only after evaluating memory/resource impact.
- UNSUPPORTED_FILE_TYPE: convert old .ppt to .pptx or export human-readable content; do not rename extensions.
- FILE_SIGNATURE_MISMATCH or LOAD_ERROR: the content does not match the extension or the archive is corrupt.
- DUPLICATE_DOCUMENT: the same SHA-256 already exists in that course.
- SCANNED_PDF_REQUIRES_OCR: perform authorized OCR, verify text, and attach a checksum-bound transcription/reingest.

## Document stays queued or processing

FastAPI BackgroundTasks run in the web process. Check the API log and ingestion job error. A process restart can interrupt an in-flight local job; use retry_failed_document internally or upload again only after verifying duplicate state. A production queue is the future upgrade for long-running/high-volume ingestion.

## Empty or irrelevant answer

1. Confirm the selected course and document status ready.
2. Inspect document chunkCount and source locator quality.
3. Run a direct FTS query or retrieval unit test with key terminology.
4. Check whether extraction produced text; scanned PDFs need OCR.
5. Adjust chunk size/top-k only after inspecting retrieved hits.
6. Re-embed after changing the embedding model.

Never fix retrieval by allowing cross-course results or asking the model to answer from general knowledge.

## FTS5 errors

The SQLite build must include FTS5. In Python run:

    import sqlite3
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE VIRTUAL TABLE probe USING fts5(content)")

If it fails, use a Python distribution compiled with FTS5. Do not replace keyword retrieval with a fake substring search without documenting the behavior change.

## database is locked

Confirm only one process owns each SQLite file, no GUI holds a write transaction, and the path is not on an unreliable network filesystem. WAL and busy_timeout reduce ordinary contention but do not make a disk horizontally scalable. Stop duplicate processes and retry; do not delete -wal blindly.

## Task tool call rejected

Read toolResults. Typical causes are an unknown tool, additional property, invalid date, invalid enum, empty update, or missing task. The rejection is expected safety behavior. Fix the prompt/tool selection or ask the user to disambiguate; do not weaken additionalProperties=false.

## Playwright port already in use

The suite owns ports 5173, 8000, and 8001. Stop only processes whose command lines point to this project and those exact ports. The Agent E2E database is work/e2e-agent-<pid>.sqlite3; it is isolated from data/agent.sqlite3. Do not kill unrelated Node/Python processes by executable name alone.

## Render loses data

Confirm each service has its own persistent disk mounted at /var/data and its database environment variable points inside that mount. Render's normal filesystem is ephemeral. Persistent disks require a paid service and one instance; redeploy code without deleting the disk.

## Netlify route refresh returns 404

Confirm the SPA redirect in netlify.toml is deployed and publish is apps/web/dist. Rebuild after configuration changes.
