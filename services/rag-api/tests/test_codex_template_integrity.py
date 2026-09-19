"""Full-body checksums independently compared to the owner's Word sections.

Only whitespace is normalized. The 14 opening markers share their paragraph
with copy guidance, so text following the marker is part of the source body.
No personal source path or Word dependency is needed for subsequent CI runs.
"""
import hashlib
import re

import pytest

from app.cm_update import templates


SOURCE_BODY_HASHES = {
    '01': '86b89a9480fd252d859026f55734446694a9f32ac76769d4c4d5ba0e40a35223',
    '02': '8a2d86f8f8624a34da71eb5ca072de5847c4e3192d73263b4801533a09602d10',
    '03': 'a0a85d2d085fe8f07cfc191b483774af9f99ffd7847e38fe15ff0708baf9a7a3',
    '04': '661b50a6cff524ab735aa712005da08d2918e9914fa5209790c6553e18d862c0',
    '05': '825eaf2062c2ea388f87bddee62ef0112007c0ea9476387d686ac45db19143e9',
    '06': '2f620d91e00d204dfcef856169892b25a66c27c1f7ca847e4c5922d086e5da22',
    '07': 'd1c68b0dbf8cb88b40e2276578f54797b2d2285e76a69509d2fd6e2258181ddd',
    '08': 'be3a11c4e3fe47c3da149b075fb3bbbb28cf342b4f0ee9cebeb4b6464ae9b634',
    '09': '4562fa527a2f297a0291956f55e6e56481be5797936a2690f6a40cbd6b21c94b',
    '10': '32467acd9cac24f7d75c0c0991e01bb0e4669ddd085b70e583f6c297cb205e9b',
    '11': '7a6ca3a604f40c9afb2330b27ef011a035c60f012aff64c7f32701db083abdbc',
    '12': 'cda869f88d5a6f2ce893eccb66deac6aa9ad4b49686fb9c1a2b60e8dfce5f9a2',
    '13': '8009d5f31f85e79cdef7748ec377644b4df694c345b056d08386071bcdd24d76',
    '14': '8b3720d8acbd6730765105be0103ac006774a93ce484db815a891c6f77e6d729',
    'EXERCISE': '72ef181492a3d2164d49a06e584fab89dcde7a786a90ca7dff09b3a80e3c3a46',
    'PROBLEM': '20c9583e787a6c238f5829f91c479107334ba4ff80b821949fcab922c3e7d127',
    'EXPLANATION': 'd0287ac76f1713982b3165de18b4b21c4ef98d06a77df6515ed9e32fd9a13342',
}


@pytest.mark.parametrize('key,expected', SOURCE_BODY_HASHES.items())
def test_complete_source_marked_body_preserved(key, expected):
    loaders = {'EXERCISE': templates.exercise_prompt, 'PROBLEM': templates.problem_prompt,
               'EXPLANATION': templates.explanation_prompt}
    body = loaders[key]() if key in loaders else templates.template_body(key)
    assert body
    normalized = re.sub(r'\s+', '', body)
    assert hashlib.sha256(normalized.encode('utf-8')).hexdigest() == expected


def test_other_retains_full_cross_disciplinary_teaching_contract():
    body = templates.template_body('OTHER')
    # Completeness follows the actual required clauses, not an invented length.
    for required in ('中文精讲', 'English Definition', '为什么学', '内部怎样工作',
                     '来源冲突', '二至五章', '三至五个递进检查问题', 'ciallo',
                     '代码没有运行就说明未执行', '不编造课程大纲', '不重新输出整套目录'):
        assert required in body
    assert 'CS3481' not in body, 'OTHER must not assign another course the CS3481 identity'
