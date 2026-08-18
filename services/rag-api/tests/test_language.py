from app.tutor.language import detect_language, language_instruction


def test_detects_chinese_and_preserves_english_technical_terms() -> None:
    result = detect_language("什么是 DBSCAN 的 core point？")

    assert result == "zh-CN"
    assert "English technical term" in language_instruction("auto", result)
    assert "中文" in language_instruction("auto", result)


def test_detects_english_question() -> None:
    result = detect_language("Why does complete-link avoid the chaining effect?")

    assert result == "en"
    assert "English" in language_instruction("auto", result)


def test_explicit_bilingual_preference_overrides_detected_language() -> None:
    instruction = language_instruction("bilingual", "en")

    assert "中文" in instruction
    assert "English" in instruction


def test_short_ambiguous_text_uses_chinese_when_it_contains_han_characters() -> None:
    assert detect_language("没懂") == "zh-CN"
    assert detect_language("why?") == "en"
