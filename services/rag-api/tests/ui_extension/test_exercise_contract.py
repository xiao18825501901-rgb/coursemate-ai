import json

import pytest

from app.cm_update.exercise_contract import ExerciseContractError, parse_exercise_output


def test_v2_accepts_reordered_unicode_escaped_formula_and_code_content():
    raw = json.dumps({
        "references": ["S1"],
        "answer_steps": [
            {"text": "先计算 $x^2$。\n```python\nprint(\"你好\")\n```", "title": "代入公式"},
            {"text": "得到结论：\\(x=2\\)。", "title": "核对结论"},
        ],
        "question": "给定中文条件与转义字符 \\\"quoted\\\"，请计算变量 x 并说明依据。",
    }, ensure_ascii=False)
    parsed = parse_exercise_output(raw, {"S1"})
    assert parsed["version"] == "exercise.v2"
    assert parsed["references"] == ["S1"]
    assert [step["ordinal"] for step in parsed["steps"]] == [1, 2]
    assert len({step["step_id"] for step in parsed["steps"]}) == 2
    assert "```python" in parsed["steps"][0]["text"]


def test_v2_rejects_reference_not_present_in_authorized_context():
    raw = json.dumps({
        "question": "This is a complete synthetic question with enough context.",
        "answer_steps": [{"title": "Compute", "text": "Synthetic private answer."}],
        "references": ["S2"],
    })
    with pytest.raises(ExerciseContractError, match="INVALID_EXERCISE_REFERENCES"):
        parse_exercise_output(raw, {"S1"})
