"""Operator-only isolated quota context; no budget/client/qualification writer."""

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.config import Settings
from app.db import Database
from app.errors import ApiError

if TYPE_CHECKING:
    from app.learning.structured_calls import ModelCallClaim


@dataclass(frozen=True)
class ReleaseEvalContext:
    database: Database
    isolated_root: Path
    authorize_slot: Callable[["ModelCallClaim", dict[str, Any]], None]
    database_path: Path = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "database_path", self.database.path.resolve(strict=True))

    @classmethod
    def for_operator(
        cls,
        *,
        database: Database,
        settings: Settings,
        isolated_root: Path,
        authorize_slot: Callable[["ModelCallClaim", dict[str, Any]], None],
    ) -> "ReleaseEvalContext":
        context = cls(database, Path(isolated_root).resolve(strict=True), authorize_slot)
        context._isolation(settings, database)
        if not callable(authorize_slot):
            raise ApiError(403, "RELEASE_EVAL_SCOPE_REQUIRED", "An operator scope is required.")
        return context

    def _isolation(self, settings: Settings, database: Database) -> None:
        root = self.isolated_root.resolve(strict=True)
        path = database.path.resolve(strict=True)
        if (
            settings.app_env not in {"test", "development"}
            or database is not self.database
            or path != self.database_path
            or not root.is_dir()
            or not path.is_relative_to(root)
            or settings.database_path.resolve() != path
            or path.as_posix().startswith("/srv/coursemate/data/")
        ):
            raise ApiError(
                403,
                "RELEASE_EVAL_ISOLATION_REQUIRED",
                "An isolated lab is required.",
            )
        for env_name in ("RAG_DATABASE_PATH", "DATABASE_PATH"):
            declared = os.environ.get(env_name)
            if declared and Path(declared).resolve() != path:
                raise ApiError(
                    403,
                    "RELEASE_EVAL_DATABASE_CONFLICT",
                    "Database paths differ.",
                )

    def verify(
        self,
        settings: Settings,
        database: Database,
        claim: "ModelCallClaim",
        identity: dict[str, Any],
    ) -> None:
        try:
            self._isolation(settings, database)
            self.authorize_slot(claim, dict(identity))
        except ApiError:
            raise
        except Exception:
            raise ApiError(
                403,
                "RELEASE_EVAL_SCOPE_INVALID",
                "The release scope is no longer valid.",
            ) from None


def reject_http_release_eval() -> None:
    if os.environ.get("COURSEJESUS_EXECUTION_CONTEXT", "").upper() == "RELEASE_EVAL":
        raise RuntimeError("RELEASE_EVAL_OPERATOR_ONLY_NOT_HTTP")
