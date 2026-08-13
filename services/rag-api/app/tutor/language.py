import re
from typing import Literal

LanguagePreference = Literal["auto", "zh-CN", "en", "bilingual"]
DetectedLanguage = Literal["zh-CN", "en"]

HAN_CHARACTER = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def detect_language(text: str) -> DetectedLanguage:
    """Use a deterministic, privacy-preserving language signal for response mirroring."""

    return "zh-CN" if HAN_CHARACTER.search(text) else "en"


def language_instruction(
    preference: LanguagePreference,
    detected: DetectedLanguage,
) -> str:
    selected: LanguagePreference = detected if preference == "auto" else preference
    if selected == "zh-CN":
        return (
            "请使用自然、清晰的简体中文教学。保留重要的 English technical term，"
            "首次出现时使用“English term（中文解释）”格式；不要把整篇回答硬翻译成英文。"
        )
    if selected == "bilingual":
        return (
            "使用中文为主、English 为辅的双语教学；关键概念同时给出准确的中文解释和 "
            "English technical term，避免逐句机械翻译。"
        )
    return "Answer in clear, natural English and preserve established technical terminology."
