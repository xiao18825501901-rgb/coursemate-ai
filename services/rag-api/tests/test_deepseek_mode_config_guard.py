"""Config-boundary guards for the DeepSeek generation mode.

``test_production_budget_config.py`` pins the Qwen config rejections; these are
the DeepSeek counterparts.  They exist because a deployment switch is performed
by editing environment variables, and ``Settings.validate()`` is the only thing
standing between a misconfigured environment and generation on the wrong
provider, host, or model.  Nothing here contacts a network.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.cm_update.app import create_app
from app.cm_update.config import Settings
from app.cm_update.provider import DeepSeekProvider, DisabledProvider

BASE_URL_ERROR = 'An explicit HTTPS DeepSeek base URL (api.deepseek.com) is required'
MODEL_ERROR = 'Only the verified deepseek-flash model is accepted for generation'
CREDENTIAL_ERROR = 'Backend DeepSeek credential is missing'
PRICING_ERROR = 'Production DeepSeek pricing configuration is required'


def deepseek_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        'environment': 'test',
        'provider_mode': 'deepseek',
        'deepseek_base_url': 'https://api.deepseek.com',
        'deepseek_key': 'test-not-real',
        'deepseek_model': 'deepseek-flash',
        'deepseek_protocol': 'responses',
        'allow_billable': True,
    }
    values.update(overrides)
    return Settings(**values)


def production_deepseek_settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        'environment': 'production',
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
    return deepseek_settings(**values)


def test_provider_mode_defaults_to_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unset mode must never silently become a paid provider."""
    monkeypatch.delenv('CMUI_PROVIDER_MODE', raising=False)

    assert Settings(environment='development').provider_mode == 'disabled'


def test_present_credentials_do_not_select_a_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Supplying keys is not a request to spend money: the mode stays explicit."""
    monkeypatch.delenv('CMUI_PROVIDER_MODE', raising=False)

    settings = Settings(
        environment='development',
        deepseek_key='test-not-real',
        qwen_key='test-not-real',
    )

    assert settings.provider_mode == 'disabled'


def test_unknown_provider_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match='Unknown provider mode'):
        Settings(environment='test', provider_mode='deepseek-flash').validate()


@pytest.mark.parametrize(
    'base_url',
    [
        'https://qwen.example.test/v1',
        'https://dashscope.aliyuncs.com/compatible-mode/v1',
        'https://api.deepseek.com/v1',
        'https://api.deepseek.com/region/cn',
        'http://api.deepseek.com',
        'http://127.0.0.1:8788',
        'https://api.deepseek.com:8443',
        'https://user:secret@api.deepseek.com',
        'https://api.deepseek.com?trace=1',
        'https://api.deepseek.com#fragment',
        'https://api.deepseek.com.evil.example.test',
        '',
    ],
)
def test_deepseek_mode_rejects_every_base_url_outside_the_allowlist(base_url: str) -> None:
    """Only an explicit ``https://api.deepseek.com`` base with an empty path."""
    settings = deepseek_settings(deepseek_base_url=base_url)

    with pytest.raises(ValueError, match=re.escape(BASE_URL_ERROR)):
        settings.validate()


def test_deepseek_mode_accepts_the_official_base_url() -> None:
    deepseek_settings().validate()


def test_deepseek_mode_requires_a_backend_credential() -> None:
    settings = deepseek_settings(deepseek_key='')

    with pytest.raises(ValueError, match=re.escape(CREDENTIAL_ERROR)):
        settings.validate()


@pytest.mark.parametrize(
    'model',
    ['qwen3.8-max', 'deepseek-reasoner', 'deepseek-chat', 'DeepSeek-Flash', 'deepseek-flash '],
)
def test_deepseek_mode_rejects_any_unverified_model(model: str) -> None:
    settings = deepseek_settings(deepseek_model=model)

    with pytest.raises(ValueError, match=re.escape(MODEL_ERROR)):
        settings.validate()


def test_deepseek_mode_does_not_require_or_read_qwen_credentials() -> None:
    """The two paid modes are independent: deepseek never falls back to Qwen."""
    settings = deepseek_settings(qwen_key='', qwen_base_url='', qwen_model='qwen3.8-max')
    settings.validate()

    provider = DeepSeekProvider(settings)

    assert provider.model == 'deepseek-flash'
    assert provider.base_url == 'https://api.deepseek.com'
    assert provider.key == 'test-not-real'


def test_qwen_mode_still_validates_without_deepseek_credentials() -> None:
    """The added DeepSeek branch must not tighten the historical Qwen mode."""
    settings = Settings(
        environment='test',
        provider_mode='qwen',
        qwen_base_url='https://qwen.example.test/v1',
        qwen_key='test-not-real',
        deepseek_key='',
    )

    settings.validate()


@pytest.mark.parametrize(
    'field',
    [
        'operation_usd_baseline',
        'operation_input_usd_per_million',
        'operation_output_usd_per_million',
    ],
)
def test_production_deepseek_rejects_each_missing_pricing_value(
    tmp_path: Path, field: str
) -> None:
    settings = production_deepseek_settings(tmp_path, **{field: ''})

    with pytest.raises(ValueError, match=re.escape(PRICING_ERROR)):
        settings.validate()


def test_production_deepseek_accepts_explicit_positive_pricing(tmp_path: Path) -> None:
    production_deepseek_settings(tmp_path).validate()


@pytest.mark.parametrize(
    'field',
    [
        'operation_usd_baseline',
        'operation_input_usd_per_million',
        'operation_output_usd_per_million',
    ],
)
def test_production_qwen_still_reports_the_qwen_pricing_error(tmp_path: Path, field: str) -> None:
    """A DeepSeek-shaped pricing gap must not be reported as a Qwen one."""
    settings = production_deepseek_settings(
        tmp_path, provider_mode='qwen', qwen_base_url='https://qwen.example.test/v1',
        qwen_key='test-not-real', **{field: ''},
    )

    with pytest.raises(ValueError, match='Production Qwen pricing configuration is required'):
        settings.validate()


def test_boot_refuses_a_misconfigured_deepseek_env_before_creating_state(tmp_path: Path) -> None:
    """``create_app`` validates before it opens the database or picks a provider.

    A bad switch-window environment must fail loudly at construction rather than
    at the first request, and it must not leave a half-initialised data
    directory behind.
    """
    data_dir = tmp_path / 'data'
    settings = deepseek_settings(
        deepseek_base_url='https://qwen.example.test/v1', data_dir=data_dir,
    )

    with pytest.raises(ValueError, match=re.escape(BASE_URL_ERROR)):
        create_app(settings, provider=DisabledProvider())

    assert not data_dir.exists()


def test_boot_accepts_a_validated_deepseek_environment(tmp_path: Path) -> None:
    """The verified DeepSeek configuration is bootable through the real root."""
    settings = deepseek_settings(data_dir=tmp_path / 'data')

    app = create_app(settings, provider=DisabledProvider())

    assert app is not None
    assert settings.provider_mode == 'deepseek'
