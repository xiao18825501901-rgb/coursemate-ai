# R16 independent identity upstream contract

Read-only source inspection found no production registered-user HTTP directory client in `cm_update` or `ui_extension`. The existing `ui_extension/identity.py` resolves an already authenticated subject; it does not list registered users. The revised `/people` route can page local `cmui_users`, which still excludes registered accounts that have never opened the new UI.

The new independent test file is `services/rag-api/tests/test_codex_directory_upstream.py`. Proposed implementation seam (an engineering choice, not a previously existing API):

```python
app.cm_update.directory.ClerkDirectoryClient(http_client: httpx.AsyncClient)
await client.fetch_users()  # complete registered identity records, server-side only
app.cm_update.directory.sync_directory(db, users)  # persisted, version-aware projection
```

Tests replace only HTTP transport with `httpx.MockTransport`, using an `.invalid` hostname and synthetic token. The API assertions use the real mounted V3 fixture with isolated databases and automatic student verification disabled. No real identity registration sync was authorized or executed.

## RED result

**4 failed, 2 dependency warnings, 6.22 seconds**, exit 1. All four currently fail at the explicit missing-client-module assertion. Consequently, this run proves the missing implementation seam; the deeper HTTP, projection, and privacy assertions have not yet executed and must be reported as pending rather than reproduced privacy leaks.

The pending contracts are:

1. Enumerate multiple identity API pages (100-row first page), deduplicate an overlapping subject, and preserve the record with the newest `updated_at` when an older duplicate appears on a later page. The synthetic registration set has 125 unique users, including accounts never projected locally.
2. Synchronize 25 registered nonvisitors and browse all through `/people` with omitted query and three 10-item pages. Public responses must expose stable opaque addresses and handles, without raw Clerk subjects, email, phone, or private metadata.
3. Preserve local non-discoverable preferences and user blocks during sync; exclude explicit banned/deleted registrations.
4. Persist identity update ordering so stale replay cannot resurrect a deleted registration.

Deletion in these contract tests is a trusted normalized identity event (`deleted=True`), not a claim that the live list endpoint returns deletion tombstones. The production integration must obtain/verify such events through its chosen identity adapter. Full-snapshot absence handling must not infer deletion from an incomplete fetch.

Reproduction from the D-drive repository:

```powershell
$env:CMUI_ALLOW_BILLABLE='false'
$env:CMUI_PROVIDER_MODE='test'
$env:CMUI_ENV='test'
$env:CMUI_AUTO_VERIFY_NEW_USERS='false'
$env:CMUI_DATA_DIR=''
$env:PYTHONPATH='services/rag-api'
& 'work/codex-audit/venv/Scripts/python.exe' -m pytest services/rag-api/tests/test_codex_directory_upstream.py -q --basetemp=work/codex-audit/directory-upstream-temp
```

Missing credentials do not prevent implementing or exercising this client contract. Actual Clerk access and synchronization remain separately authorized external work.
