from decimal import Decimal
import json

from app.cm_update.config import Settings
from app.cm_update.provider import QwenProvider


def configured_provider(**overrides: object) -> QwenProvider:
    settings = Settings(
        provider_mode="qwen",
        qwen_base_url="https://qwen.example.test/v1",
        qwen_key="test-not-real",
        allow_billable=True,
        operation_input_usd_per_million="2",
        operation_output_usd_per_million="10",
        **overrides,
    )
    return QwenProvider(settings)


def test_thinking_estimate_reserves_both_qwen_stages_and_the_plan_as_work_input() -> None:
    provider = configured_provider(prompt_tokens=120, answer_tokens=240)

    estimate = provider.estimate_generation(
        {"name": "CS3481", "code": "CS3481"},
        "解释 DBSCAN 的核心点",
        {"language": "zh-CN"},
        [{"id": "S1", "text": "课程材料"}],
        [],
        "teach",
        teaching_mode="thinking",
    )

    assert estimate.stage_count == 2
    assert estimate.output_tokens == 360
    assert estimate.input_tokens > 120
    assert estimate.usd > Decimal("0")
    assert [stage["name"] for stage in estimate.audit()["stages"]] == ["planner", "teacher"]


def test_image_generation_estimate_includes_the_server_enforced_visual_token_bound() -> None:
    provider = configured_provider()

    estimate = provider.estimate_generation(
        {"name": "CS3481", "code": "CS3481"},
        "解这张题图",
        {},
        [],
        [],
        "problem",
        attachments=[{"data_url": "data:image/png;base64,xxx"}],
    )

    assert estimate.image_inputs == 1
    assert estimate.input_tokens >= 2562


def test_classification_estimate_uses_the_same_frozen_bundle_as_the_live_call() -> None:
    provider = configured_provider()
    bundle = {
        'materials_revision': 'frozen-synthetic-revision',
        'text_samples': [
            {'document_id': 'doc-1', 'version_id': 'v-1', 'text': 'CS3481 data structures'}
        ],
    }

    estimate = provider.estimate_classification(bundle)
    messages = provider.classification_messages(bundle)

    assert estimate.stage_count == 1
    assert estimate.stages[0]['name'] == 'classification'
    assert estimate.stages[0]['output_tokens_upper_bound'] == min(provider.cfg.prompt_tokens, 1200)
    assert json.loads(messages[1]['content']) == bundle
