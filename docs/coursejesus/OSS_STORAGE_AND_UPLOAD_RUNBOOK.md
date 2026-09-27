# Private OSS storage and upload runbook

Status: source implemented; production resources not yet available  
Production region: `cn-hangzhou`  
Application candidate: `5a3c1070c2753083a1a9032de96d136c28eda6d7`

## Hard gate

Do not deploy or switch storage while either condition remains true:

1. `free - existing reservations - task peak < max(10 GiB, 20% filesystem)`;
2. the ECS runtime cannot obtain a prefix-scoped RAM role for a private OSS
   bucket in `cn-hangzhou`.

At the last read-only check, production had only 971,333,632 bytes available;
the zero-peak reserve alone was 10,737,418,240 bytes. No OSS application
settings or attached instance role were visible. The gate is currently closed.

## Owner resource card

The following console actions require the Alibaba Cloud account owner/MFA. Do
not paste a password, verification code, private key, access key, or token into
chat.

1. ECS console → Hangzhou → instance `i-bp1f0vqhds2341pdqqiy`
   (`47.114.34.175`) → expand the system disk from 40 GiB to at least 80 GiB.
   Expansion is not accepted until the guest filesystem reports enough free
   space for the formula above and a backup/rehearsal peak.
2. OSS console → Hangzhou → create or nominate one **private** Standard bucket.
   Block public access, enable server-side encryption, and set lifecycle rules
   only for incomplete multipart uploads and the explicitly named quarantine
   prefix. Do not set a rule that deletes canonical originals or backup
   versions.
3. RAM console → create an ECS-trusted instance role, grant only the nominated
   bucket and CourseJesus prefix, and attach it to the instance. Alibaba's
   official attachment procedure is documented at
   <https://www.alibabacloud.com/help/en/ecs/user-guide/attach-an-instance-ram-role-to-an-ecs-instance>.
4. Record the bucket name, internal endpoint, region, chosen prefix, encryption
   setting, versioning setting, and role name in the release evidence. Bucket
   policy guidance is at
   <https://www.alibabacloud.com/help/en/oss/user-guide/ram-policy/> and
   <https://www.alibabacloud.com/help/en/oss/user-guide/access-control-base-on-ram-policy>.

The application currently needs object read/write within one prefix. It does
not need bucket administration or a global `*` resource. Validate the exact
RAM action names in the policy editor rather than copying an unverified policy.

## Bucket decisions

- Encryption: enable OSS server-side encryption; see
  <https://www.alibabacloud.com/help/en/oss/user-guide/data-encryption/>.
- Versioning: if enabled, document its retention/cost and test overwrite
  behavior. OSS notes that versioning changes `forbid-overwrite` behavior. The
  application therefore uses content-addressed canonical keys and validates the
  full SHA-256, size, and returned version ID; it never treats ETag as MD5.
  See <https://www.alibabacloud.com/help/en/oss/user-guide/overview-78/>.
- Multipart: incomplete parts need a lifecycle rule; see
  <https://www.alibabacloud.com/help/en/oss/user-guide/multipart-upload> and
  <https://www.alibabacloud.com/help/en/oss/user-guide/overview-54/>.
- Public endpoint: leave unset unless a later reviewed feature explicitly needs
  it. Downloads and previews remain authorized backend reads or short-lived
  scoped URLs.

## Runtime configuration

Use an ECS RAM role, not static credentials. Store only non-secret resource
coordinates in the root-owned application environment:

```text
STORAGE_BACKEND=aliyun_oss
STORAGE_CACHE_DIR=/srv/coursemate/cache/storage
STORAGE_CACHE_MAX_BYTES=10737418240
OSS_REGION=cn-hangzhou
OSS_BUCKET=<private-bucket>
OSS_ENDPOINT=<cn-hangzhou-internal-endpoint>
OSS_OBJECT_PREFIX=coursejesus/production
```

Keep `AUTO_KNOWLEDGE_MAP_ALLOW_BILLABLE=false` during storage rollout. The
default direct-upload signature lifetime is 600 seconds and is bounded to
60–900 seconds. Signatures are limited to one quarantine object and expected
metadata; the browser cannot choose a canonical key.

## Staged execution

1. Verify the attached role through the instance metadata service without
   printing credentials. Verify bucket privacy and prefix denial outside the
   application prefix.
2. Build a fresh consistent database/files/manifest recovery unit. Its
   `SHA256SUMS` must cover every regular file, including `manifest.json`; no
   symlink, directory, or extra file is permitted.
3. Archive the unit:

   ```text
   python scripts/archive_storage_backup.py archive \
     --backup-dir <verified-backup-dir> \
     --receipt <root-only-receipt.json>
   ```

4. Restore-verify it into an isolated filesystem directory:

   ```text
   python scripts/archive_storage_backup.py verify-restore \
     --receipt <root-only-receipt.json> \
     --restore-root <empty-isolated-restore-dir>
   ```

5. Run the storage migration in plan-only mode. It must enumerate immutable
   document versions without writes:

   ```text
   python scripts/migrate_storage_to_oss.py
   ```

6. Apply and restore-test one explicit version before expanding:

   ```text
   python scripts/migrate_storage_to_oss.py --apply \
     --version-id <document-version-id>
   python scripts/migrate_storage_to_oss.py --verify-restore \
     --version-id <document-version-id> \
     --restore-root <empty-isolated-restore-dir>
   ```

7. Verify authorized preview Range reads, download SHA-256, citation retrieval,
   Canvas import, sharing snapshot, problem image, assessment attachment, and
   backup restore. Only then expand the migration batch.

## Direct-upload contract

The web client asks the backend for one short-lived quarantine upload session,
uploads bytes directly to OSS, and sends a completion claim. The backend then:

1. performs an authorized ranged/full read as required;
2. computes and verifies actual SHA-256 and size instead of trusting the browser;
3. promotes to a content-addressed canonical key;
4. writes the storage object and immutable document-version linkage;
5. enqueues existing ingestion only after database admission succeeds;
6. records an orphan receipt if upload succeeded but admission lost a race.

Campus/admin path ingestion streams each source file to OSS. A sealed batch
fires exactly one compact-map event, and parser concurrency remains bounded.
Never use `ossutil sync --delete` and never proxy a 100 GiB corpus through the
small API server.

## Deletion and rollback

Local originals remain authoritative during dual-read. Deleting one server
copy is allowed only when that exact object has: immutable OSS bytes, SHA/size/
version receipt, valid database references, isolated restore evidence, a
separate recovery unit, and tested OSS-unavailable fallback. This release does
not automate canonical deletion.

Never delete `D:\Canvas`, `D:\Canvas-DG`, SQLite WAL files, the only backup, or
any user original. On storage failure, stop new direct-upload issuance, retain
quarantine/canonical receipts, switch application reads back to `local`, and
restore the prior immutable application release. Do not rewrite already issued
document-version identities.
