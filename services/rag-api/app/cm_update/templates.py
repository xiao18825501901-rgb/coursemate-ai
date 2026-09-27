"""Template Registry: the 14 professional teaching templates + OTHER, the three
problem/explanation prompts, and the internal plan-writer instruction.

Templates are versioned.  V2 (Qwen/DeepSeek re-import, 16 files) is the default
for new requests; V1 is preserved on disk and by `registry("V1")` so old
conversations and classification evidence keep the exact template version they
recorded.  The 题目 (`problem_prompt`) and 详解 (`explanation_prompt`) prompts
are NOT part of the 16-file replacement set and keep returning their V1 files.

Every template body was extracted from the owner's original Word documents
(read-only import) between the document's own 【可复制 Prompt 开始】…
【可复制 Prompt 结束】 markers; the OTHER template is Appendix A of the
governing prompt, and PLAN_WRITER is Appendix B. Files are stored under
`cm_update/prompts/` so runtime never depends on the source path.

Registry rows carry the original-file sha256 and the extracted-body sha256 for
audit (TEMPLATE_REGISTRY_AND_CLASSIFICATION.md references the same hashes).
"""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_PROMPTS_DIR = Path(__file__).parent / "prompts"

# template_id -> (file, level, professional_name) — V1 (historical evidence)
_TEMPLATE_FILES: dict[str, tuple[str, str, str]] = {
    "01": ("01_GRAD_BUSINESS_INFORMATION_SYSTEMS_V1.txt", "graduate", "商务资讯系统"),
    "02": ("02_GRAD_COMPUTER_SCIENCE_V1.txt", "graduate", "计算机科学"),
    "03": ("03_GRAD_DATA_SCIENCE_V1.txt", "graduate", "数据科学"),
    "04": ("04_GRAD_ELECTRONIC_INFORMATION_ENGINEERING_V1.txt", "graduate", "电子资讯工程学"),
    "05": ("05_GRAD_ENGINEERING_MANAGEMENT_V1.txt", "graduate", "工程管理学"),
    "06": ("06_GRAD_MATERIALS_ENGINEERING_NANOTECH_V1.txt", "graduate", "材料工程及纳米科技"),
    "07": ("07_GRAD_BIOMEDICAL_ENGINEERING_V1.txt", "graduate", "生物医学工程"),
    "08": ("08_GRAD_ARTIFICIAL_INTELLIGENCE_V1.txt", "graduate", "人工智能"),
    "09": ("09_GRAD_BUSINESS_DATA_ANALYTICS_V1.txt", "graduate", "商业及数据分析"),
    "10": ("10_GRAD_INNOVATION_ENTREPRENEURSHIP_V1.txt", "graduate", "创新创业"),
    "11": ("11_UG_COMPUTER_SCIENCE_TECHNOLOGY_V1.txt", "undergraduate", "计算机科学与技术"),
    "12": ("12_UG_INTELLIGENT_MANUFACTURING_V1.txt", "undergraduate", "智能制造"),
    "13": ("13_UG_MATERIALS_V1.txt", "undergraduate", "材料"),
    "14": ("14_UG_ENERGY_V1.txt", "undergraduate", "能源"),
}

# template_id -> (file, level, professional_name) — V2 (content templates; same
# ids/levels/professionals as V1, re-imported from the V2 Qwen/DeepSeek DOCX).
_TEMPLATE_FILES_V2: dict[str, tuple[str, str, str]] = {
    "01": ("01_GRAD_BUSINESS_INFORMATION_SYSTEMS_V2.txt", "graduate", "商务资讯系统"),
    "02": ("02_GRAD_COMPUTER_SCIENCE_V2.txt", "graduate", "计算机科学"),
    "03": ("03_GRAD_DATA_SCIENCE_V2.txt", "graduate", "数据科学"),
    "04": ("04_GRAD_ELECTRONIC_INFORMATION_ENGINEERING_V2.txt", "graduate", "电子资讯工程学"),
    "05": ("05_GRAD_ENGINEERING_MANAGEMENT_V2.txt", "graduate", "工程管理学"),
    "06": ("06_GRAD_MATERIALS_ENGINEERING_NANOTECH_V2.txt", "graduate", "材料工程及纳米科技"),
    "07": ("07_GRAD_BIOMEDICAL_ENGINEERING_V2.txt", "graduate", "生物医学工程"),
    "08": ("08_GRAD_ARTIFICIAL_INTELLIGENCE_V2.txt", "graduate", "人工智能"),
    "09": ("09_GRAD_BUSINESS_DATA_ANALYTICS_V2.txt", "graduate", "商业及数据分析"),
    "10": ("10_GRAD_INNOVATION_ENTREPRENEURSHIP_V2.txt", "graduate", "创新创业"),
    "11": ("11_UG_COMPUTER_SCIENCE_TECHNOLOGY_V2.txt", "undergraduate", "计算机科学与技术"),
    "12": ("12_UG_INTELLIGENT_MANUFACTURING_V2.txt", "undergraduate", "智能制造"),
    "13": ("13_UG_MATERIALS_V2.txt", "undergraduate", "材料"),
    "14": ("14_UG_ENERGY_V2.txt", "undergraduate", "能源"),
}

OTHER_TEMPLATE_ID = "OTHER"
_OTHER_FILE = "15_OTHER_GENERAL_V1.txt"
_OTHER_FILE_V2 = "15_OTHER_GENERAL_V2.txt"
_EXERCISE_FILE = "EXERCISE_PROMPT_V1.txt"
_EXERCISE_FILE_V2 = "EXERCISE_PROMPT_V2.txt"
_EXERCISE_RUNTIME_FILE = "EXERCISE_RUNTIME_CONTRACT_V2.txt"
_PROBLEM_FILE = "PROBLEM_PROMPT_V1.txt"
_EXPLANATION_FILE = "EXPLANATION_PROMPT_V1.txt"
_PLAN_WRITER_FILE = "PLAN_WRITER_INSTRUCTION_V1.txt"

_SUPPORTED_VERSIONS = ("V1", "V2")


def _sha256(path: Path) -> str:
    # Prompt manifests hash normalized UTF-8 text. Keep that identity stable on
    # Windows checkouts where Git may materialize CRLF line endings.
    normalized = path.read_text(encoding="utf-8")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _body_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _check_version(version: str) -> str:
    if version not in _SUPPORTED_VERSIONS:
        raise ValueError(f"unknown template version: {version!r}")
    return version


@lru_cache(maxsize=None)
def registry(version: str = "V2") -> dict[str, dict[str, Any]]:
    """Return {template_id: {id, level, professional, version, file, body,
    body_sha256, file_sha256}} for the requested version.

    V2 is the default (new requests); V1 is retained for historical evidence
    and old conversations that recorded their template version.
    """
    version = _check_version(version)
    files = _TEMPLATE_FILES if version == "V1" else _TEMPLATE_FILES_V2
    other_file = _OTHER_FILE if version == "V1" else _OTHER_FILE_V2
    out: dict[str, dict[str, Any]] = {}
    for template_id, (file_name, level, professional) in files.items():
        path = _PROMPTS_DIR / file_name
        body = path.read_text(encoding="utf-8").strip()
        out[template_id] = {
            "id": template_id,
            "level": level,
            "professional": professional,
            "version": version,
            "file": file_name,
            "body": body,
            "body_sha256": _body_hash(body),
            "file_sha256": _sha256(path),
        }
    other_path = _PROMPTS_DIR / other_file
    other_body = other_path.read_text(encoding="utf-8").strip()
    out[OTHER_TEMPLATE_ID] = {
        "id": OTHER_TEMPLATE_ID,
        "level": "unknown",
        "professional": "其他／跨学科／暂无法可靠归类",
        "version": version,
        "file": other_file,
        "body": other_body,
        "body_sha256": _body_hash(other_body),
        "file_sha256": _sha256(other_path),
    }
    return out


def template_body(template_id: str, version: str = "V2") -> str | None:
    entry = registry(version).get(template_id)
    return entry["body"] if entry else None


def other_template(version: str = "V2") -> str:
    """Return the OTHER (cross-disciplinary) template body for the version."""
    return registry(version)[OTHER_TEMPLATE_ID]["body"]


def exercise_prompt(version: str = "V2") -> str:
    version = _check_version(version)
    file_name = _EXERCISE_FILE if version == "V1" else _EXERCISE_FILE_V2
    return (_PROMPTS_DIR / file_name).read_text(encoding="utf-8").strip()


def exercise_runtime_contract() -> str:
    return (_PROMPTS_DIR / _EXERCISE_RUNTIME_FILE).read_text(encoding="utf-8").strip()


def problem_prompt() -> str:
    return (_PROMPTS_DIR / _PROBLEM_FILE).read_text(encoding="utf-8").strip()


def explanation_prompt() -> str:
    return (_PROMPTS_DIR / _EXPLANATION_FILE).read_text(encoding="utf-8").strip()


def plan_writer_instruction() -> str:
    return (_PROMPTS_DIR / _PLAN_WRITER_FILE).read_text(encoding="utf-8").strip()


def registry_json() -> str:
    """Registry export WITHOUT template bodies (for admin/settings views),
    reporting both V1 and V2 entries."""
    slim = []
    for version in _SUPPORTED_VERSIONS:
        slim.extend(
            {
                "id": entry["id"],
                "level": entry["level"],
                "professional": entry["professional"],
                "version": entry["version"],
                "file": entry["file"],
                "body_sha256": entry["body_sha256"],
                "file_sha256": entry["file_sha256"],
            }
            for entry in registry(version).values()
        )
    return json.dumps({"templates": slim}, ensure_ascii=False, indent=2)
