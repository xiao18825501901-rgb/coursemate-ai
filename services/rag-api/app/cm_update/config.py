from dataclasses import dataclass, field
from pathlib import Path
import os
import json
from urllib.parse import urlparse


def flag(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() == 'true'


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.getenv('CMUI_DATA_DIR', './work/local-data')).resolve())
    environment: str = field(default_factory=lambda: os.getenv('CMUI_ENV', 'development'))
    auth_mode: str = field(default_factory=lambda: os.getenv('CMUI_AUTH_MODE', 'development'))
    allowed_origins: tuple[str, ...] = field(default_factory=lambda: tuple(x.strip() for x in os.getenv('CMUI_ALLOWED_ORIGINS', 'http://127.0.0.1:8787,http://localhost:8787').split(',') if x.strip()))
    clerk_issuer: str = field(default_factory=lambda: os.getenv('CLERK_ISSUER', ''))
    clerk_jwt_key: str = field(default_factory=lambda: os.getenv('CLERK_JWT_KEY', '').replace('\\n', '\n'))
    clerk_audience: str = field(default_factory=lambda: os.getenv('CLERK_AUDIENCE', ''))
    clerk_publishable_key: str = field(default_factory=lambda: os.getenv('CLERK_PUBLISHABLE_KEY', ''))
    admin_ids: tuple[str, ...] = field(default_factory=lambda: tuple(x for x in os.getenv('CMUI_ADMIN_IDS', '').split(',') if x))
    provider_mode: str = field(default_factory=lambda: os.getenv('CMUI_PROVIDER_MODE', 'disabled'))
    allow_billable: bool = field(default_factory=lambda: flag('CMUI_ALLOW_BILLABLE'))
    qwen_base_url: str = field(default_factory=lambda: os.getenv('CMUI_QWEN_BASE_URL', ''))
    qwen_key: str = field(default_factory=lambda: os.getenv('CMUI_QWEN_API_KEY', ''))
    qwen_model: str = field(default_factory=lambda: os.getenv('CMUI_QWEN_MODEL', 'qwen3.8-max'))
    qwen_protocol: str = field(default_factory=lambda: os.getenv('CMUI_QWEN_PROTOCOL', 'chat_completions'))
    timeout: float = field(default_factory=lambda: float(os.getenv("CMUI_MODEL_TIMEOUT", "180")))
    prompt_tokens: int = field(default_factory=lambda: int(os.getenv("CMUI_PROMPT_TOKENS", "2500")))
    answer_tokens: int = field(default_factory=lambda: int(os.getenv("CMUI_ANSWER_TOKENS", "6500")))
    max_upload_bytes: int = 20 * 1024 * 1024
    max_user_bytes: int = 250 * 1024 * 1024
    max_files: int = 100
    integration_mode: str = field(default_factory=lambda: os.getenv('CMUI_INTEGRATION_MODE', 'standalone'))
    api_base: str = field(default_factory=lambda: os.getenv('CMUI_PUBLIC_API_BASE', '/api/ui/v1'))
    web_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parents[2] / 'web' / 'dist')
    verification_secret: str = field(default_factory=lambda: os.getenv('CMUI_VERIFICATION_SECRET', ''))
    auto_verify_new_users: bool = field(default_factory=lambda: flag('CMUI_AUTO_VERIFY_NEW_USERS'))

    def validate(self) -> None:
        if self.environment not in {'development','test','production'}: raise ValueError('Unknown environment')
        if self.provider_mode not in {'disabled','qwen','test'}: raise ValueError('Unknown provider mode')
        if not 256<=self.prompt_tokens<=12000 or not 256<=self.answer_tokens<=16000: raise ValueError('Model output bounds invalid')
        if not 10<=self.timeout<=300: raise ValueError('Model timeout invalid')
        if self.auth_mode not in {'development', 'clerk', 'injected'}:
            raise ValueError('Unsupported authentication mode')
        if self.environment == 'production':
            marker=self.web_dir/'build-info.json'
            if marker.exists() and json.loads(
                marker.read_text(encoding='utf-8')
            ).get('not_for_production'):
                raise ValueError('Offline browser-verification runtime cannot be deployed; build the real React application')
            if self.auth_mode == 'development':
                raise ValueError('Development login is forbidden in production')
            if self.provider_mode == 'test':
                raise ValueError('Test provider is forbidden in production')
            if self.integration_mode != 'integrated':
                raise ValueError('Production requires the reviewed V3 domain adapter; do not seed a replacement database')
            if any(urlparse(x).scheme != 'https' for x in self.allowed_origins):
                raise ValueError('Production origins must be HTTPS')
            if not self.verification_secret:
                raise ValueError('CMUI_VERIFICATION_SECRET is required in production')
            if self.auto_verify_new_users:
                raise ValueError('CMUI_AUTO_VERIFY_NEW_USERS is a test/dev convenience and is forbidden in production')
        if self.auth_mode == 'clerk' and not (self.clerk_issuer and self.clerk_jwt_key):
            raise ValueError('Clerk issuer and public verification key are required')
        if self.provider_mode == 'qwen':
            p = urlparse(self.qwen_base_url)
            if p.scheme != 'https' or not p.hostname or p.username or p.password or p.query or p.fragment:
                raise ValueError('An explicit HTTPS provider base URL without credentials/query/fragment is required')
            if not self.qwen_key:
                raise ValueError('Backend Qwen credential is missing')
        if self.qwen_protocol not in {'chat_completions', 'responses'}:
            raise ValueError('Unknown model protocol')
