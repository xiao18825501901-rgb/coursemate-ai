# CAMPUS SOURCE AND PUBLICATION MATRIX (task C1)

**State of this document.** This is the round-44 result of the *read-only* scan required by task
C1 — "读取本机 `D:\Canvas`、`D:\Canvas-DG`，核验后通过正式入库和课程发布流程扩充校园课程".
Everything below is measured on this machine by `scripts/scan_campus_inventory.py`. Nothing was
downloaded, moved, renamed or deleted, and **nothing has been published**: the scan produces a
review list, never a publication right.

Sources (both kept in place, never uploaded to Git or Netlify):

```text
D:\Canvas\           + D:\Canvas\_download_manifest.csv
D:\Canvas-DG\        + D:\Canvas-DG\_download_manifest.csv
```

Command that produced the artefacts:

```text
python scripts/scan_campus_inventory.py --root D:\Canvas --root D:\Canvas-DG \
  --out docs/coursejesus/LOCAL_CAMPUS_INVENTORY.csv \
  --full-out work/current-change/campus-inventory-full.csv \
  --summary work/current-change/campus-inventory-summary.json
```

## 1. Reconciliation: manifest versus disk

| Measurement | `D:\Canvas` | `D:\Canvas-DG` | Total |
|---|---|---|---|
| manifest rows | 201 | 1718 | 1919 |
| files found on disk | 202 | 1719 | 1921 (includes both manifests) |
| manifest rows with the file present and the same size | 201 | 1718 | **1919** |
| rows missing on disk | 0 | 0 | **0** |
| rows whose byte count disagrees with the disk | 0 | 0 | **0** |
| files on disk that the manifest does not list | 0 | 0 | **0** |
| total bytes on disk | 773,418,255 (737.6 MiB) | 8,095,437,975 (7.54 GiB) | 8,868,856,230 (8.26 GiB) |

The two roots reconcile exactly: every manifest row has its file with a matching size, and no
file exists outside the manifest. SHA-256 was computed for all 1919 files (streaming, 1 MiB
chunks), so `sha256` in the inventory identifies the *local bytes* rather than repeating what
Canvas said. That is the limit of this check: it proves the local copy is internally consistent
and deduplicable; it does not prove the local bytes still match what Canvas serves today.

Manifest columns differ between the roots, and the inventory records it rather than hiding it:

| Root | columns |
|---|---|
| `D:\Canvas` | `course_id, course, category, filename, bytes, path, status` — **no `file_id`, no `term`** |
| `D:\Canvas-DG` | `course_id, course, term, course_code, file_id, filename, bytes, path, status` |

Every `D:\Canvas` row therefore carries `source_file_id` empty with the note
`manifest has no file_id column/value`. It also means same-name/different-id detection can only
be complete for the DG root.

## 2. Classification policy (what the five categories mean here)

The scanner assigns exactly one category per file, deterministically, and records the reason in
`classification_reason`. Order matters: privacy first, then information boards, then training,
then teaching material.

| Category | Rule (in order) | Consequence in this project |
|---|---|---|
| `PERSONAL_OR_RESTRICTED` | filename, then path, contains a privacy marker | **Never** a campus-course candidate; review list |
| `INFORMATION` | path is under an announcement / scholarship area | Not a campus course; may stay as an unpublished admin resource |
| `TRAINING` | path or name marks training material (orientation, workshop, mandatory) | Not a campus course by default; needs a human decision |
| `ACADEMIC_TEACHING` | path is a teaching-material area (`01_主课`, lecture/tutorial/lab/assignment...), or, for the DG root, the file sits directly inside a `<term>/<course>/` layout | **Candidate** for the campus library — candidate only, still `NEEDS_REVIEW` |
| `UNKNOWN_REVIEW` | nothing matched | Review list |

Two marker classes are matched differently, and the difference was forced by the real data:
English markers must start at a word boundary and must not be followed by a lowercase letter,
CJK markers are substring matches. The first version used plain substring matching and produced
three real misclassifications, all now pinned by tests:

| File (real) | Wrong | Right | Why the first version failed |
|---|---|---|---|
| `CS2312\Grader.java`, `IGrade.java` | `PERSONAL_OR_RESTRICTED` | `ACADEMIC_TEACHING` | substring `grade` inside a Java class name |
| `CB2300\...Week 2--personality and emotion...pdf` | `PERSONAL_OR_RESTRICTED` | `ACADEMIC_TEACHING` | substring `personal` inside `personality` |
| `ME1921\学生分组.xlsx` | `TRAINING` | `PERSONAL_OR_RESTRICTED` | the training check ran before the privacy check, so a student grouping list was filed as training material |

## 3. Classification outcome (measured)

| Category | Files | Share |
|---|---|---|
| `ACADEMIC_TEACHING` (candidates) | 1715 | 89.3% |
| `INFORMATION` | 170 | 8.9% |
| `PERSONAL_OR_RESTRICTED` | 21 | 1.1% |
| `TRAINING` | 13 | 0.7% |
| `UNKNOWN_REVIEW` | 2 | 0.1% |

Parse class (what a later ingestion step would face):

| Class | Files | Meaning |
|---|---|---|
| `PARSEABLE` | 1682 | text/office/pdf/html/source — the corpus candidate set |
| `UNKNOWN` | 174 | extension not in either list; must be inspected before any claim |
| `DOWNLOAD_ONLY` | 65 | media/archives: kept, never claimed as model-ready |

**Publishable now: 0.** `publishable_now` is 0 by construction — the tool has no code path that
grants a publication right, and the summary says so in words. Turning candidates into published
course material requires the rights decision in §5 and the real ingestion pipeline (task C3).

## 4. Per-course matrix (all 34 courses in both roots)

`files` counts every row of that course in the manifest; `classes` shows the classification mix,
so a course whose review items are mixed in is visible instead of being summarised as "academic".

| Institution | Canvas course_id | Term | Course | Files | Bytes | Classes |
|---|---|---|---|---|---|---|
| CityU(DG) | 560 | Semester B 2025_26 | Problem Solve & Programming CS2312 | 428 | 1.77GB | ACADEMIC_TEACHING:424, PERSONAL_OR_RESTRICTED:4 |
| CityU(DG) | 240 | Semester A 2024_25 | Funda. of Internet App. Dev. CS2204 | 406 | 91.72MB | ACADEMIC_TEACHING:406 |
| CityU | 50961 | — | CS Announcement | 154 | 225.32MB | INFORMATION:154 |
| CityU(DG) | 233 | Semester A 2024_25 | General Physics I PHY1201 | 87 | 88.53MB | ACADEMIC_TEACHING:87 |
| CityU(DG) | 216 | Semester A 2024_25 | Calculus & Basic Linear Algebra I MA1200 | 68 | 36.52MB | ACADEMIC_TEACHING:66, PERSONAL_OR_RESTRICTED:2 |
| CityU(DG) | 318 | Semester B 2024_25 | Calculus & Basic Linear Algebra II MA1201 | 57 | 91.32MB | ACADEMIC_TEACHING:54, PERSONAL_OR_RESTRICTED:3 |
| CityU(DG) | 257 | Semester A 2024_25 | University English I GE1401 | 56 | 590.64MB | ACADEMIC_TEACHING:55, TRAINING:1 |
| CityU(DG) | 630 | Summer Term 2026 | Fundamentals of Data Science **CS3481** | 55 | 44.57MB | ACADEMIC_TEACHING:49, PERSONAL_OR_RESTRICTED:6 |
| CityU(DG) | 383 | Semester A 2025_26 | 思想道德与法治 IP1902 | 54 | 2.32GB | ACADEMIC_TEACHING:54 |
| CityU(DG) | 525 | Semester B 2025_26 | Operating Systems CS3103 | 49 | 24.72MB | ACADEMIC_TEACHING:49 |
| CityU(DG) | 544 | Semester B 2025_26 | Database Systems CS3402 | 49 | 67.23MB | ACADEMIC_TEACHING:49 |
| CityU(DG) | 358 | Semester A 2025_26 | Discrete Mathematics MA2185 | 47 | 101.48MB | ACADEMIC_TEACHING:47 |
| CityU(DG) | 441 | Semester A 2025_26 | Computer Networks CS3201 | 45 | 100.61MB | ACADEMIC_TEACHING:45 |
| CityU(DG) | 500 | Semester B 2025_26 | Data Structures CS3334 | 37 | 11.07MB | ACADEMIC_TEACHING:37 |
| CityU(DG) | 426 | Semester A 2025_26 | Computer Programming CS2310 | 36 | 16.79MB | ACADEMIC_TEACHING:36 |
| CityU(DG) | 489 | Semester B 2025_26 | 走在前列的广东实践 IP2903 | 36 | 163.39MB | ACADEMIC_TEACHING:35, PERSONAL_OR_RESTRICTED:1 |
| CityU(DG) | 629 | Summer Term 2026 | Art & Science of Data **GE2324** | 36 | 95.55MB | ACADEMIC_TEACHING:36 |
| CityU(DG) | 308 | Semester B 2024_25 | Persuasion in Everyday Life GE2248 | 35 | 98.57MB | ACADEMIC_TEACHING:34, PERSONAL_OR_RESTRICTED:1 |
| CityU(DG) | 367 | Semester A 2025_26 | Computer Organization CS2115 | 25 | 35.82MB | ACADEMIC_TEACHING:25 |
| CityU(DG) | 317 | Semester B 2024_25 | AI - Past Present and Future GE2340 | 24 | 58.17MB | ACADEMIC_TEACHING:24 |
| CityU(DG) | 548 | Semester B 2025_26 | 中国近现代史纲要 IP2902 | 21 | 1.33GB | ACADEMIC_TEACHING:21 |
| CityU(DG) | 268 | Semester A 2024_25 | Fundamentals of Advertising GE2001 | 16 | 34.58MB | ACADEMIC_TEACHING:16 |
| CityU | 56548 | — | CS Scholarship | 16 | 16.01MB | INFORMATION:16 |
| CityU(DG) | 336 | Semester B 2024_25 | Freshman Workshop II ME1921 | 13 | 62.99MB | TRAINING:12, PERSONAL_OR_RESTRICTED:1 |
| CityU(DG) | 384 | Semester A 2025_26 | Management CB2300 | 13 | 24.44MB | ACADEMIC_TEACHING:13 |
| CityU | 70574 | — | CS4182 Computer Graphics | 12 | 487.49MB | ACADEMIC_TEACHING:12 |
| CityU(DG) | 487 | Semester B 2025_26 | Intro Comp Prob Model CS2402 | 10 | 9.64MB | ACADEMIC_TEACHING:10 |
| CityU | 70578 | — | CS4335 Design and Analy of Algorithms | 10 | 2.40MB | ACADEMIC_TEACHING:10 |
| CityU | 70579 | — | CS4394 Info Security and Mgt | 9 | 6.34MB | ACADEMIC_TEACHING:7, PERSONAL_OR_RESTRICTED:2 |
| CityU(DG) | 359 | Semester A 2025_26 | Sems on Contemp Tech I CS2611 | 5 | 8.02MB | ACADEMIC_TEACHING:5 |
| CityU(DG) | 370 | Semester A 2025_26 | Physical Education III PE2911 | 5 | 149.34MB | ACADEMIC_TEACHING:4, PERSONAL_OR_RESTRICTED:1 |
| CityU(DG) | 214 | Semester A 2024_25 | 体育1A PE1911 | 2 | 161.46MB | ACADEMIC_TEACHING:2 |
| CityU(DG) | 628 | Summer Term 2026 | 社会实践 IP3902 | 2 | 1.06MB | ACADEMIC_TEACHING:2 |
| CityU(DG) | 319 | Semester B 2024_25 | Intro.toComputer Programming CS1302 | 1 | 21.72KB | ACADEMIC_TEACHING:1 |

Term distribution: Semester A 2024_25 635, Semester B 2025_26 630, Semester A 2025_26 230,
Semester B 2024_25 130, Summer Term 2026 93, no term (the `D:\Canvas` root, which has no `term`
column) 203.

Course identity: the unique key going forward is **institution origin + Canvas course_id**; and
the terms above are what make "same code, different semester" a different offering rather than a
merge. CS3481 (`630`) and GE2324 (`629`) both appear here as **Summer Term 2026** offerings of
courses that also exist in production with their own `course_id`, published trees, history and
grades — this scan only inventories local files and does not touch either (see §6).

## 5. Files needing a decision (the review list)

21 files are `PERSONAL_OR_RESTRICTED` and 13 are `TRAINING`. They fall into three groups, and the
distinction matters because only one of them is really about privacy:

| Group | Count | What it is | Recommendation |
|---|---|---|---|
| Personal/administrative data | 8 | `StudentList.txt`, `AttendanceLog.txt`, `To_PartAB_Given_Attendance*.xlsx`, `Assignment Submission Gu…`, `学生分组.xlsx`, `体测分组.xls`, `案例分析：社会实践报告 张三 学号xxx.doc`, `Overall Feedback on GE2248 …` | **Do not publish.** These are class lists, attendance, submissions and individual feedback |
| Instructor answers / solutions | 13 | tutorial and exercise answer sets (`Tutorial_1_answers.pdf`, `Week_2_answers_to_examples.pdf`, `Answer t…` MA1200/MA1201, `tut1/2/3_answer.pdf` CS3481, `CS3103-Tutorial-3-answersheet.docx`) | Not personal data, but republishing to *every registered user* is a different audience than the class. One owner decision covers all 13 |
| Mandatory-training material | 13 | 12 military-theory/security slides inside ME1921 "Freshman Workshop II" + 1 library orientation | Not a campus-course candidate as classified; decide once whether ME1921 counts as teaching material |

The concrete names, paths, sizes and hashes for all of these are in
`work/current-change/campus-inventory-full.csv` (working copy) — deliberately **not** in the
committed inventory. In `docs/coursejesus/LOCAL_CAMPUS_INVENTORY.csv` the 21
`PERSONAL_OR_RESTRICTED` rows keep their `sha256`, size, course, term and reason but have
`filename`/`relative_path` replaced with `REDACTED_PERSONAL_OR_RESTRICTED`, so the committed
artefact does not put personal filenames into Git history while still letting a reviewer act on
each row. Nothing else is redacted.

## 6. Duplicates, versions and cross-course reuse (dedupe input for C2/C3)

* **76 groups of byte-identical files** (same SHA-256) — the ingestion step must hash first and
  reuse rather than re-index. Largest groups come from CS2204 (16, 14 and 9-copy groups) and
  CS2312 (`data001-*` 9 copies, `data002-*` 9, `data003-*` 5), i.e. the same handout uploaded
  under several Canvas file ids.
* **15 same-name groups with different Canvas file ids** — for example `Lab_Report_Template.docx`
  vs `Lab_Report_Template-17604.docx`, `Huawei poster.png` vs `Huawei poster-1.png`,
  `The D. H. Chen Foundation Scholarship.zip` vs `…-1.zip`. Per the pack, same name is **not** an
  identity: both are kept, and only `origin + course_id + file_id (+ version)` decides.
* One duplicate crosses two different courses: `chp5.pdf` is byte-identical in **CS3481** and
  **GE2324**. Both are production courses, so the "identical hash → skip re-ingest" rule has a
  real instance here rather than being hypothetical.

## 7. Preservation of the existing courses

* This scan is read-only: no file in either root was modified (a test asserts the tool cannot
  write into a source root), and no file was uploaded anywhere.
* `CS3481` and `GE2324` are present locally as Summer Term 2026 offerings; their production
  `course_id`, published trees, history, grades and pair bindings were not touched by anything in
  this round — no production system was contacted at all.
* The local copies contain 6 and 0 `PERSONAL_OR_RESTRICTED` rows respectively; in particular the
  CS3481 tutorial answer files must not be re-published as campus material by any bulk step.

## 8. Honest limits

1. **Classification is a review aid, not a rights decision.** It reads names and paths, never
   file contents, so it can both over- and under-flag. Its output is a work list for a human, and
   the three real misclassifications in §2 are evidence that a first version will be wrong.
2. **DG candidates are candidates by layout.** A file sitting inside `<term>/<course>/` is treated
   as teaching material because of where it is, not because its content was read.
3. **Local bytes, not Canvas truth.** The hashes prove identity and deduplication within this
   machine. They cannot prove the file is unmodified since download, and they say nothing about
   whether redistribution is allowed.
4. **No institution column exists.** Institution attribution comes from the source-root
   convention and is labelled `SOURCE_ROOT_CONVENTION` on every row; it is not Canvas API
   evidence.
5. **`D:\Canvas` has no `file_id` column**, so same-name/different-id detection is only complete
   for the DG root; the affected rows say so in `notes`.
6. **Nothing here is published, uploaded, migrated or cost anything.** The next step (C3) needs
   the rights decision in §5 and the real `IngestionService` path, not a fixture.
