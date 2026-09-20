"""Production Qwen services must reject incomplete preflight pricing."""
from pathlib import Path

import pytest

from app.cm_update.config import Settings


def production_qwen_settings(tmp_path: Path, **overrides: object) -> Settings:
    values = {
        'environment': 'production',
        'provider_mode': 'qwen',
        'qwen_base_url': 'https://qwen.example.test/v1',
        'qwen_key': 'test-not-real',
        'auth_mode': 'clerk',
        'clerk_issuer': 'https://issuer.example.test',
        'clerk_jwt_key': 'synthetic-public-key',
        'integration_mode': 'integrated',
        'allowed_origins': ('https://qqttai.example.test',),
        'verification_secret': 'synthetic-secret',
        'web_dir': tmp_path / 'web',
        'operation_usd_baseline': '0.20',
        'operation_input_usd_per_million': '2.40',
        'operation_output_usd_per_million': '7.20',
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.parametrize(
    'field',
    [
        'operation_usd_baseline',
        'operation_input_usd_per_million',
        'operation_output_usd_per_million',
    ],
)
def test_production_qwen_rejects_each_missing_pricing_value(tmp_path: Path, field: str) -> None:
    settings = production_qwen_settings(tmp_path, **{field: ''})

    with pytest.raises(ValueError, match='Production Qwen pricing configuration is required'):
        settings.validate()


def test_production_qwen_accepts_explicit_positive_pricing(tmp_path: Path) -> None:
    production_qwen_settings(tmp_path).validate()
