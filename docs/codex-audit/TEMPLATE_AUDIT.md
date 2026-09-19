# Independent full-template audit

Date: 2026-09-19. Scope: R04 source completeness. Originals were read only using DOCX ZIP/XML, without Word automation, cloud conversion, model calls, or modifications. Only the 14 numbered professional Word files and `做一题prompt.docx`, `题目prompt.docx`, `详解prompt.docx` were opened. Document text was treated as source data.

## Result

**All 17 Word-derived runtime bodies exactly match their marked source sections after removing whitespace. Missing paragraphs: zero. Substantive differences: zero.** Sections 5–10 of the professional templates are included. This is text integrity evidence, not proof of model compliance or teaching quality.

Source directory: `C:\Users\Hp\xwechat_files\wxid_lpdn28neu0i112_ecd6\msg\file\2026-09`.

Runtime directory verified in this repository: `services/rag-api/app/cm_update/prompts/`. Loader: `services/rag-api/app/cm_update/templates.py`. Runtime files are TXT resources, not Word files and not a `templates/` subdirectory. Runtime does not read the original WeChat directory.

Extraction uses `word/document.xml`, paragraphs in document order including table paragraphs, joined Word text runs. Start is the paragraph beginning with `【可复制 Prompt 开始】` (professional) or `【完整 Prompt 开始】` (three task templates); end is the later paragraph beginning with the corresponding end marker. Text after the opening marker in the same paragraph is retained. This matters: the professional opening paragraph includes an additional 61 non-whitespace characters of copying guidance; omitting that paragraph produced a false initial difference, corrected by retaining its trailing text. No source or runtime text was changed to obtain agreement.

| ID / source document | Compared paragraphs after opening paragraph | Normalized characters including opening remainder | Result |
|---|---:|---:|---|
| 01 研究生 商务资讯系统 | 180 | 11549 | Exact |
| 02 研究生 计算机科学 | 180 | 11448 | Exact |
| 03 研究生 数据科学 | 180 | 11520 | Exact |
| 04 研究生 电子资讯工程学 | 179 | 11389 | Exact |
| 05 研究生 工程管理学 | 180 | 11389 | Exact |
| 06 研究生 材料工程及纳米科技 | 180 | 11380 | Exact |
| 07 研究生 生物医学工程 | 180 | 11360 | Exact |
| 08 研究生 人工智能 | 180 | 11420 | Exact |
| 09 研究生 商业及数据分析 | 180 | 11415 | Exact |
| 10 研究生 创新创业 | 180 | 11381 | Exact |
| 11 本科 计算机科学与技术 | 180 | 11322 | Exact |
| 12 本科 智能制造 | 180 | 11327 | Exact |
| 13 本科 材料 | 179 | 11175 | Exact |
| 14 本科 能源 | 180 | 11392 | Exact |
| 做一题prompt.docx | 46 | 2796 | Exact |
| 题目prompt.docx | 46 | 2723 | Exact |
| 详解prompt.docx | 49 | 2633 | Exact |

## Source-file SHA256 ledger

These are the original DOCX byte hashes, independently read from the authorized directory. Body checksum baselines are in `tests/test_codex_template_integrity.py`.

```text
01 5c026770017ebc0bda910c8034ce0452da00f3ebbb5dd0df473fce2d0cad4653
02 536d65a6d131e0e48ae724ec5a992ca0e3cb7e6f2893a8aecc3df9ecf9603e04
03 60fd91599a7d76d0c732711f9038c3c05b74ae7faf907c20b04123afccbba006
04 feb908f1f6ce563ff42caf2927cb46806f3b4c562fb58e53cf76d9f5350c43be
05 c2c4511edc8b5281c01bb3dbf0b91abf86d76b111d169414e547fb158927238a
06 2d166dc9a730acf6abc61df1f5bde91743bd004f8456e726c71301fc46d72126
07 cb8ffc17513f57bb85cc307abd8e5d9d69364767b1f12b7b9527769045a24f1b
08 d4e3f5600c069fe376c43c8a4bc0a69c6aadb4a1e4dccd293d49a1246cc49a6e
09 5a4c6c56ee56d3d9802a980e25dc71e7454a3844bb60e5fefd6064e4c9a157ea
10 0d66948ad4e45e7bc786a0e6e0a28cfa74b456722a1798be96089ec452c931c2
11 57386a7aa65a090793dcdc1d7f3eb582fecbbe400fafaca674bba7ee79f25e1b
12 f107b31daad59196be61b36efd7aa56ab57cd3be25e801df80bd68ad76b1b7e3
13 1933588cd355fbaa922851d060ed75953675552b0ef8c2d8e3bce8be8b40bbaf
14 6fc002908914cf15e8afc589f298e6db757de35e99f06e058c11139283bf6c14
EXERCISE c513cfa4d6c44cd5f3dd0d0c75d689c9184a65a22f81acb9ef17f82890f2d507
PROBLEM f5a93c8e9e1a97bb8471b7f3b42b460b205df8b0ba8ac71d530821ac54830899
EXPLANATION 674d773f28ffe459b3ffef36be607433160639054e71c7ac49a6778f2ec54a9f
```

The loader module's top-level claim that registry rows carry the **original-file** hash is inaccurate: `registry().file_sha256` computes the runtime TXT file hash. It must not be cited as a Word-source checksum. The ledger above supplies the independently verified original hashes. This documentation correction does not require changing the matching template bodies.

## OTHER and inherited CS3481 principles

`15_OTHER_GENERAL_V1.txt` is a substantive 2,927-character, ten-section general template. Read against the runtime historical `CS3481_ORIGINAL_TEMPLATE_V1.txt` and R04 requirements, it retains Chinese explanation/English expression, course-evidence fidelity, Why/What/How/application/exam flow, discipline-sensitive teaching, material/data/code/chart links, one-to-five chapter policy, three-to-five progressive checks with `ciallo`, continuation and revision rules, and separate covered/mastered evidence. It does not assign CS3481 identity to unrelated courses. No replacement was necessary.

The DSH claim that OTHER is exactly an earlier “Appendix A” was not independently established from an original appendix in this bounded audit. The current audit prompt specifies OTHER's required principles rather than a complete replacement body. Thus semantic coverage is verified; exact historical appendix provenance remains unverified. The legacy CS3481 runtime text was used as a principle comparator, not claimed as a newly verified binary `.doc` extraction.

## Automated verification

`services/rag-api/tests/test_codex_template_integrity.py` pins all 17 independently verified normalized Word-body hashes and checks OTHER's required substantive clauses. It avoids dependence on an owner's personal directory in future CI runs.

```powershell
$env:PYTHONPATH='services/rag-api'
$env:CMUI_ALLOW_BILLABLE='false'
& 'work/codex-audit/venv/Scripts/python.exe' -m pytest services/rag-api/tests/test_codex_template_integrity.py -q --basetemp=work/codex-audit/template-audit-temp
```

Final result: **18 passed in 0.23 seconds**. Initial execution had 17 passed and one invalid audit assertion requiring OTHER to exceed an invented 3,000-character minimum; no such minimum exists in the requirements. That assertion was removed and replaced by the already enumerated substantive clause checks. No application source or template was changed, and no failing product behavior was concealed.
