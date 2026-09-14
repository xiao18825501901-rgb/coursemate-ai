"""Injection contract. Existing CourseMate domain/schema is deliberately not guessed."""
from typing import Protocol, Any

class DomainPort(Protocol):
    async def call(self, operation: str, subject: str, payload: dict, credential: str = '') -> Any:
        """Reuse verified V3 services for courses/files/tasks/knowledge/context/assessment.

        Must derive authorization from subject. Never accept owner from client payload.
        Operations and canonical response shapes are specified in integration/README.md.
        """
        ...


def install_ui_extension(host_app, settings, domain: DomainPort, subject_resolver, *, mount_path='/ui-extension', provider=None):
    """Mount into an existing FastAPI application without replacing its routes/lifespan.

    Call once during host construction, before the server starts. The host application's
    existing startup/shutdown hooks are retained. User must supply real adapters; this
    helper intentionally cannot discover or guess a production V3 database schema.

    `provider` is a test seam only: production mounts pass none and get the real
    Qwen/disabled provider selected from `settings`.
    """
    from contextlib import asynccontextmanager
    from .app import create_app
    if not mount_path.startswith('/') or mount_path=='/' or '?' in mount_path:
        raise ValueError('Use a distinct extension path, not the original application root')
    if any(getattr(route,'path',None)==mount_path for route in host_app.routes):
        raise ValueError('Extension mount path already exists')
    if settings.integration_mode!='integrated' or settings.auth_mode!='injected':
        raise ValueError('Host mount requires integrated domain and verified injected identity')
    settings.api_base=mount_path.rstrip('/')+'/api/ui/v1'
    ui=create_app(settings,domain=domain,subject_resolver=subject_resolver,provider=provider)
    original=host_app.router.lifespan_context
    @asynccontextmanager
    async def combined_lifespan(app):
        async with original(app):
            async with ui.router.lifespan_context(ui):
                yield
    host_app.router.lifespan_context=combined_lifespan
    host_app.mount(mount_path,ui)
    return ui
