# CourseMate production course content inventory

**Inventory time:** 2026-09-20 06:07 CST / 2026-09-19 22:07 UTC

**Production application:** `aa3ffc250c2c4584f35dceea1a9ceec61123fdef`

**Production data release:** `/srv/coursemate/data/releases/20260919T202006Z`

**Inventory method:** read-only queries against the live RAG and UI SQLite databases. No README, deployment template, old report, fixture, or seed data was used as the source of the counts below.

## Result

The live database contains exactly two platform-managed public official/campus courses: `cs3481` and `ge2324`. No private, workspace, or shared course is included in this inventory.

The previously reported `CS3481 = 0 published nodes` is stale. The current live database has a PUBLISHED CS3481 official tree with 22 published nodes.

| Course | Name | Type / display | Visibility | Student verification | Documents ready / indexed | Valid OFFICIAL versions | Current official tree | Published nodes | Atomic / composite | Active-tree Specs published | REQUIRED items | Older DRAFT trees | Readiness |
| --- | --- | --- | --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | --- | --- |
| `cs3481` | CS3481 | official / campus | public | required | 38 / 38 | 38 | v3 `official-tree-15fd76815c754d148064e5e8872ad35c` | 22 | 15 / 7 | 15 / 15 | 15 | v1, v2 | READY / PUBLISHED |
| `ge2324` | GE2324 | official / campus | public | required | 28 / 28 | 28 | v3 `official-tree-168ad777b4a549debd6614d75c77a09d` | 21 | 14 / 7 | 14 / 14 | 15 | v1, v2 | READY / PUBLISHED |

Document indexing totals are 924 chunks for CS3481 and 1,012 chunks for GE2324.

## Current tree and teaching specification detail

### CS3481

- Current official tree: version 3, `PUBLISHED`.
- Tree members: 22; 15 ATOMIC and 7 COMPOSITE.
- Every ATOMIC member binds a Teaching Spec version.
- All 15 active-tree Teaching Specs have `PUBLISHED` metadata.
- Every ATOMIC member has at least one REQUIRED Teaching Item; active-tree total is 15 REQUIRED, 0 RECOMMENDED, and 0 OPTIONAL.
- Course-wide historical metadata contains 17 Teaching Spec versions. The extra two are not active-tree requirements and are not counted as current published coverage.
- Active official evidence: 42 material-evidence rows, 42 distinct chunks, 15 document versions.
- Current PUBLISHED nodes contain 22 `major=CS` values. This legacy node field is not the UI Template Registry assignment.

### GE2324

- Current official tree: version 3, `PUBLISHED`.
- Tree members: 21; 14 ATOMIC and 7 COMPOSITE.
- Every ATOMIC member binds a Teaching Spec version.
- All 14 active-tree Teaching Specs have `PUBLISHED` metadata.
- Every ATOMIC member has at least one REQUIRED Teaching Item; active-tree total is 15 REQUIRED, 0 RECOMMENDED, and 0 OPTIONAL.
- Course-wide historical metadata contains 19 Teaching Spec versions. The extra five are not active-tree requirements and are not counted as current published coverage.
- Active official evidence: 50 material-evidence rows, 46 distinct chunks, 16 document versions.
- Current PUBLISHED nodes contain 21 `major=CS` values. This legacy node field is not the UI Template Registry assignment.

RECOMMENDED and OPTIONAL Teaching Items are supported by the schema but are not required to calculate `LEARNED`; both current trees use REQUIRED-only minimum coverage contracts. This is disclosed rather than represented as additional content that does not exist.

## Publication audit trail

| Course | Approved request | Snapshot | Active release | Submitted actor hash | Reviewer hash | Reviewed at | Review note |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CS3481 | `knowledge_publication_87071faf24204eb58ce5ac125aebf59d` | `snapshot_b16adad434984878be20d7af3f70fc46` | `release_cce007b525ae4994bbfa2c444886b2dd` | `42e46c352632` | `9814ec167915` | 2026-09-18 12:58:53.821 UTC | Second administrator independent review (M6F). |
| GE2324 | `knowledge_publication_b1cf69762f7a490d9eba39907f298bbf` | `snapshot_cff2eeac765241c9b57ff40326f64adb` | `release_f7dce39f596747968e1cba0e9c76aa01` | `42e46c352632` | `9814ec167915` | 2026-09-18 12:58:53.957 UTC | Second administrator independent review (M6F). |

The hashes above are the first 12 hexadecimal characters of SHA-256 over the actor identifiers; raw identity values are intentionally omitted. Older rejected publication requests remain as immutable audit history. There is exactly one ACTIVE `OFFICIAL_KNOWLEDGE` release per course.

## Structural and source validation

The current PUBLISHED trees passed the following live-data checks:

- tree membership, parent links, and prerequisite links stay inside the correct course;
- no parent or prerequisite cycle;
- all ATOMIC members bind a current Teaching Spec and contain REQUIRED items;
- COMPOSITE members do not masquerade as teachable atomic units;
- all cited document versions and chunks exist;
- all cited sources have `OFFICIAL` scope and no owner identity;
- no workspace-private or shared-course document enters a publication snapshot;
- no fixture, synthetic, canary, internal-prompt, credential, email, or user-record marker in published node/spec content;
- snapshot resource hashes and overall snapshot hashes match current published content;
- current publication drift is zero;
- live RAG `integrity_check=ok` and `foreign_key_check=0`.

Teaching Item `evidence_ids_json` values are chunk identifiers, not `material_evidence.id` values. Validation resolves them through the live chunk/document-version relationship. CS3481 has 44 references to 42 unique valid official chunks; GE2324 has 57 references to 46 unique valid official chunks. Missing and invalid-scope references are zero.

## Template resolution

The 14-profession Template Registry plus `OTHER` is present in the deployed application. Classification is deliberately scoped by user and course because its evidence may include private workspace material. There is no global official-course classification row to publish or copy across users.

For the synthetic acceptance user, neither CS3481 nor GE2324 had a stored scoped classification. Runtime therefore used the safe `OTHER` fallback. This is an accurate fallback, not a claim that either course has been globally classified. No new paid classification call was required for content publication.

## File availability finding

All 66 official files exist in the active data release and match their recorded SHA-256 and byte size. Their immutable database paths still reference the former `/srv/coursemate/rag/uploads` root. The official-publication lock correctly rejected an attempted path mutation and the transaction rolled back.

Original downloads were restored without changing locked publication data by creating this reversible compatibility link:

```text
/srv/coursemate/rag/uploads
  -> /srv/coursemate/data/releases/20260919T202006Z/uploads
```

All 66 stored paths now resolve to matching bytes, and a production API download returned HTTP 200 with the expected 1,095,540 bytes. Any future data-release switch must atomically retarget and validate this compatibility link.

## Final inventory disposition

Both production official/campus courses are `OWNER_APPROVED_FOR_PUBLICATION` and already PUBLISHED through the normal publication workflow. No missing tree or Spec required a new generation batch in this activation run. Private courses, private workspaces, shared snapshots, and personal uploads remain excluded.
