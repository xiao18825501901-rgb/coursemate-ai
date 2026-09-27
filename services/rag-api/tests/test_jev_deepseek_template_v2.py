"""V2 template-import regressions for the Jev/DeepSeek implementation pack.

Sixteen content templates (14 professional + EXERCISE + OTHER) were imported
from the pack's normalized ``template_text_v2/`` into
``app/cm_update/prompts/`` with explicit ``_V2`` file names, and the template
registry was versioned (V1 preserved, V2 default). This module verifies:

* all 16 V2 bodies load and their file hashes equal the manifest
  ``normalized_text_sha256`` values;
* each V2 body length matches the manifest ``text_characters`` (±2);
* the 14 professional V2 bodies keep the required sections (``ciallo``,
  ``中文``, and the final-step marker — the V1 ``第十步`` renumbered to ``10.x``);
* ``problem_prompt()`` / ``explanation_prompt()`` still return the unchanged V1
  files (they are NOT part of the 16-file replacement set);
* ``EXERCISE_RUNTIME_CONTRACT_V2.txt`` still exists and the exercise.v2 parser
  still accepts a structured payload.

The manifest values below are transcribed verbatim from
``TEMPLATE_V2_MANIFEST.json`` so this test runs hermetically (no dependency on
the pack's download path).
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from app.cm_update import exercise_contract, templates

_PROMPTS_DIR = Path(templates.__file__).parent / "prompts"

_PROFESSIONAL_IDS = [f"{i:02d}" for i in range(1, 15)]

# registry_key -> (normalized_text_sha256, text_characters) from TEMPLATE_V2_MANIFEST.json
_MANIFEST: dict[str, tuple[str, int]] = {
    "01": ("c5d4f776f51387e4ee19a2cf2dae8606f49960dbf15445db4bad9f222071a2c4", 10299),
    "02": ("bda05802091f297302d0e35372f942acd3373ac79c223fa0bad20754d9abd2c1", 10179),
    "03": ("0ec885e240e09a97844d426ab37d5a966b9d36b16f0a5593ede83284bbdc4b7b", 10272),
    "04": ("b149501705218e12bce92ca0c6b47269c098b02f4608220f39f6a5379737c60b", 10110),
    "05": ("13b10083b7404f5a1e623eff64b60daf58478969784aeec6a4e8a8f547debc82", 10114),
    "06": ("2c8f470ead317c0b96fe91a9e2ce6cf874113ee76fc75d2118d49189ae5232b2", 10089),
    "07": ("a3bae564621e5131a4c3c6655b9790e48b6909084e0e9beb8bed6bb010d98ef5", 10064),
    "08": ("327b4454f697abd763d4259db08ba16341c7b5f6656f1c2528bfb55669a14acb", 10150),
    "09": ("3a73e7ad4fad10a7f74cae1042887d05e6b0bb81d8c23c206947c0e4dd392253", 10155),
    "10": ("fe5aa610f390080bffc8eb241be5d001802302737b45b84c7341fbe35b96055b", 10085),
    "11": ("8de629f3560ebdcd97dcc3e1af303bb7e669e23e14febc84feb8647f2ec40573", 10054),
    "12": ("80e6fa4a7d54ec494fd0530162c785abff5b43e1665795a903e7d4aa687b73eb", 10050),
    "13": ("df56a39073d0abe65345f08cb7638f530ff56c56c3a777f169e9324966c3d17d", 9855),
    "14": ("0f693e237e4be30ca8bb0f38b6e07282f98cc1190aee55c6281754bfc84d6375", 10132),
    "OTHER": ("651782fd957f787af4aa7942b71ae756895e018aba62b234fc0cb2eabb3eab4a", 3662),
    "EXERCISE": ("7a24bf02d0dd3b8905811f4ffe27cf655a5e93691ca78241e9d354b0dfe00456", 3314),
}

# The V1 body ends with "第十步"; the V2 re-import renumbers that final section
# to Arabic "10.x". Both are accepted as the full-body final-step marker.
_FINAL_STEP_MARKERS = ("第十步", "10.")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _normalized_file_sha256(path: Path) -> str:
    return _sha256_bytes(path.read_text(encoding="utf-8").encode("utf-8"))


def test_v2_registry_loads_15_entries_matching_manifest_hashes() -> None:
    reg = templates.registry("V2")
    assert set(reg) == {*_PROFESSIONAL_IDS, "OTHER"}

    for key, (expected_sha, expected_chars) in _MANIFEST.items():
        if key == "EXERCISE":
            continue
        entry = reg[key]
        assert entry["version"] == "V2", key
        # file_sha256 is the raw-file byte hash == manifest normalized_text_sha256.
        assert entry["file_sha256"] == expected_sha, key
        assert entry["body_sha256"] == _sha256_bytes(entry["body"].encode("utf-8")), key
        # text_characters counts the normalized text; .strip() removes at most the
        # trailing newline, so the body length stays within ±2 of the manifest count.
        assert abs(len(entry["body"]) - expected_chars) <= 2, key


def test_exercise_prompt_v2_file_matches_manifest() -> None:
    path = _PROMPTS_DIR / "EXERCISE_PROMPT_V2.txt"
    assert path.is_file()
    assert _normalized_file_sha256(path) == _MANIFEST["EXERCISE"][0]

    body = templates.exercise_prompt("V2")
    assert abs(len(body) - _MANIFEST["EXERCISE"][1]) <= 2
    assert "ciallo" in body


def test_all_16_v2_bodies_have_distinct_hashes() -> None:
    reg = templates.registry("V2")
    hashes = {entry["body_sha256"] for entry in reg.values()}
    hashes.add(_sha256_bytes(templates.exercise_prompt("V2").encode("utf-8")))
    assert len(hashes) == 16, "V2 template bodies must be distinct"


@pytest.mark.parametrize("template_id", _PROFESSIONAL_IDS)
def test_professional_v2_body_keeps_required_sections(template_id: str) -> None:
    body = templates.template_body(template_id, "V2")
    assert body
    assert "ciallo" in body
    assert "中文" in body
    assert any(marker in body for marker in _FINAL_STEP_MARKERS), template_id


def test_problem_and_explanation_prompts_are_unchanged_v1() -> None:
    """题目/详解 are NOT in the 16-file set; they must stay byte-identical to V1."""
    for file_name, loader in (
        ("PROBLEM_PROMPT_V1.txt", templates.problem_prompt),
        ("EXPLANATION_PROMPT_V1.txt", templates.explanation_prompt),
    ):
        v1_body = (_PROMPTS_DIR / file_name).read_text(encoding="utf-8").strip()
        loaded = loader()
        assert loaded == v1_body, f"{file_name} was changed"
        assert _sha256_bytes(loaded.encode("utf-8")) == _sha256_bytes(v1_body.encode("utf-8"))


def test_exercise_runtime_contract_exists_and_parses_v2_payload() -> None:
    contract_path = _PROMPTS_DIR / "EXERCISE_RUNTIME_CONTRACT_V2.txt"
    assert contract_path.is_file(), "exercise.v2 hidden-answer contract file is missing"
    assert templates.exercise_runtime_contract()

    payload = json.dumps(
        {
            "question": "给定二维样本点集合，请判断哪些点是核心点并说明理由。",
            "answer_steps": [
                {"title": "核心点判定", "text": "邻域内样本数不少于 MinPts 的点为核心点。"},
            ],
            "references": ["S1"],
        },
        ensure_ascii=False,
    )
    parsed = exercise_contract.parse_exercise_output(payload, allowed_references={"S1"})
    assert parsed["version"] == exercise_contract.EXERCISE_VERSION_V2
    assert parsed["question"].startswith("给定二维样本点集合")
    assert len(parsed["steps"]) == 1
    assert parsed["references"] == ["S1"]


def test_registry_version_lookup_and_defaults() -> None:
    v1 = templates.registry("V1")
    v2 = templates.registry("V2")
    assert v1["01"]["version"] == "V1"
    assert v1["01"]["file"] == "01_GRAD_BUSINESS_INFORMATION_SYSTEMS_V1.txt"
    assert v2["01"]["version"] == "V2"
    assert v2["01"]["file"] == "01_GRAD_BUSINESS_INFORMATION_SYSTEMS_V2.txt"
    # Default is V2; V1 stays a genuinely different import.
    assert templates.registry()["01"]["version"] == "V2"
    assert v1["01"]["body_sha256"] != v2["01"]["body_sha256"]
    assert templates.template_body("01") == v2["01"]["body"]
    assert templates.other_template() == v2["OTHER"]["body"]
    with pytest.raises(ValueError):
        templates.registry("V3")


def test_registry_json_reports_both_versions_slim() -> None:
    data = json.loads(templates.registry_json())
    entries = data["templates"]
    assert {entry["version"] for entry in entries} == {"V1", "V2"}
    assert len(entries) == 30, "15 entries per version"
    assert all("body" not in entry for entry in entries), "registry_json must omit bodies"
    # both versions share the same stable ids/professionals
    by_version = {"V1": set(), "V2": set()}
    for entry in entries:
        by_version[entry["version"]].add(entry["id"])
    assert by_version["V1"] == by_version["V2"] == {*_PROFESSIONAL_IDS, "OTHER"}
