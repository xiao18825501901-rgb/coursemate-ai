"""Jev semantic-decision layer (non-authoritative signal layer).

Public surface: :class:`~app.jev.catalog.Catalog` (the 12 definitions),
:class:`~app.jev.gateway.JevGateway` (transport/modes/bounds/receipts) and
:class:`~app.jev.service.SemanticDecisionService` (deterministic-fallback helpers).
"""

from app.jev.catalog import Catalog, DecisionDefinition, load_catalog
from app.jev.errors import (
    JevError,
    JevInvalidResponseError,
    JevNotConfiguredError,
    JevRequestError,
    JevTimeoutError,
    JevUnavailableError,
)
from app.jev.gateway import (
    Decision,
    DecisionRequest,
    FakeTransport,
    GatewayBounds,
    JevGateway,
    Receipt,
    SdkTransport,
)
from app.jev.models import CacheScope
from app.jev.service import (
    BudgetProvenance,
    DecisionResult,
    InputBudgetExceeded,
    SemanticDecisionService,
    TemplateOption,
)

__all__ = [
    "BudgetProvenance",
    "CacheScope",
    "Catalog",
    "Decision",
    "DecisionDefinition",
    "DecisionRequest",
    "DecisionResult",
    "FakeTransport",
    "GatewayBounds",
    "InputBudgetExceeded",
    "JevError",
    "JevGateway",
    "JevInvalidResponseError",
    "JevNotConfiguredError",
    "JevRequestError",
    "JevTimeoutError",
    "JevUnavailableError",
    "Receipt",
    "SdkTransport",
    "SemanticDecisionService",
    "TemplateOption",
    "load_catalog",
]
