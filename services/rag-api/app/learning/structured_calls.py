"""Durable structured calls over the sole host client and original daily allowance."""

import hashlib
import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypeVar

from pydantic import ValidationError

from app.config import Settings
from app.db import Database
from app.errors import ApiError
from app.learning.generic_provider import generic_provider_route
from app.learning.model_budget import daily_model_call_counts
from app.learning.models import Contract
from app.learning.provider import LearningProvider, ProviderCallFailure, schema_error_summary
from app.learning.release_eval import ReleaseEvalContext


@dataclass(frozen=True)
class ModelCallClaim:
    request_id: str
    owner_user_id: str
    course_id: str
    content_language: str
    verify: Callable[[], None]
    verify_transaction: Callable[[sqlite3.Connection], None] | None = None


Output = TypeVar("Output", bound=Contract)


class GenericStructuredCalls:
    def __init__(
        self,
        database: Database,
        settings: Settings,
        provider: LearningProvider,
        *,
        release_eval: ReleaseEvalContext | None = None,
    ) -> None:
        self.db, self.settings, self.provider = database, settings, provider
        if release_eval is not None and not isinstance(release_eval, ReleaseEvalContext):
            raise ApiError(403, "RELEASE_EVAL_SCOPE_REQUIRED", "An operator scope is required.")
        self.release_eval = release_eval

    def _identity_for(
        self,
        claim: ModelCallClaim,
        *,
        instructions: str,
        payload: dict[str, Any],
        role: str,
        operation_family: str,
        template_version: str,
        schema_version: str,
        max_output_tokens: int,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        route = generic_provider_route(self.settings, self.provider)
        template_hash = hashlib.sha256(instructions.encode()).hexdigest()
        input_hash = hashlib.sha256(
            json.dumps({"input": payload, "route": route}, sort_keys=True).encode()
        ).hexdigest()
        identity = {
            "owner_user_id": claim.owner_user_id,
            "course_id": claim.course_id,
            "role": role,
            "operation_family": operation_family,
            "input_hash": input_hash,
            "template_version": template_version,
            "template_hash": template_hash,
            "schema_version": schema_version,
            "content_language": claim.content_language,
            "capability_receipt_id": self.settings.cj_qwen_capability_receipt_id,
            "secret_generation_id": self.settings.cj_qwen_secret_generation_id,
            "region_label": self.provider.cache_region,
            "model_id": "qwen3.8-max",
            "reserved_output_tokens": max_output_tokens,
        }
        return identity, route

    def read_completed(
        self,
        claim: ModelCallClaim,
        schema: type[Output],
        *,
        instructions: str,
        payload: dict[str, Any],
        role: str,
        operation_family: str,
        template_version: str,
        schema_version: str,
        max_output_tokens: int,
    ) -> Output | None:
        claim.verify()
        try:
            identity, _ = self._identity_for(
                claim,
                instructions=instructions,
                payload=payload,
                role=role,
                operation_family=operation_family,
                template_version=template_version,
                schema_version=schema_version,
                max_output_tokens=max_output_tokens,
            )
        except ApiError:
            return None
        if self.release_eval is not None:
            self.release_eval.verify(self.settings, self.db, claim, identity)
        with self.db.connect() as db:
            prior = db.execute(
                "SELECT * FROM generic_llm_calls WHERE id=?", (claim.request_id,)
            ).fetchone()
        if (
            prior is None
            or prior["status"] != "COMPLETED"
            or any(prior[key] != value for key, value in identity.items())
        ):
            return None
        try:
            output = schema.model_validate_json(prior["output_json"])
        except ValidationError:
            return None
        claim.verify()
        if self.release_eval is not None:
            self.release_eval.verify(self.settings, self.db, claim, identity)
        return output

    def generate_for(
        self,
        claim: ModelCallClaim,
        schema: type[Output],
        *,
        instructions: str,
        payload: dict[str, Any],
        role: str,
        operation_family: str,
        template_version: str,
        schema_version: str,
        max_output_tokens: int,
    ) -> Output:
        claim.verify()
        identity, route = self._identity_for(
            claim,
            instructions=instructions,
            payload=payload,
            role=role,
            operation_family=operation_family,
            template_version=template_version,
            schema_version=schema_version,
            max_output_tokens=max_output_tokens,
        )

        def verify() -> None:
            claim.verify()
            if self.release_eval is not None:
                self.release_eval.verify(self.settings, self.db, claim, identity)

        verify()
        cached = None
        with self.db.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if claim.verify_transaction is not None:
                claim.verify_transaction(db)
            prior = db.execute(
                "SELECT * FROM generic_llm_calls WHERE id=?", (claim.request_id,)
            ).fetchone()
            if prior is not None:
                if any(prior[key] != value for key, value in identity.items()):
                    raise ApiError(
                        409,
                        "MODEL_ANSWER_IDENTITY_CONFLICT",
                        "The answer request changed.",
                    )
                if prior["status"] != "COMPLETED":
                    raise ApiError(
                        409,
                        "MODEL_REQUEST_UNCERTAIN",
                        "The request cannot be sent again.",
                    )
                try:
                    cached = schema.model_validate_json(prior["output_json"])
                except ValidationError:
                    raise ApiError(
                        409,
                        "MODEL_COMPLETED_RECEIPT_INVALID",
                        "The saved response cannot be reused. No new request was sent.",
                    ) from None
            else:
                user, course = daily_model_call_counts(
                    db, claim.owner_user_id, claim.course_id
                )
                if self.release_eval is None and (
                    user >= self.settings.v3_daily_model_calls_per_user
                    or course >= self.settings.v3_daily_model_calls_per_user_course
                ):
                    raise ApiError(
                        429,
                        "DAILY_MODEL_CALL_QUOTA",
                        "The daily call budget was reached.",
                    )
                columns = ["id", *identity]
                db.execute(
                    f"INSERT INTO generic_llm_calls({','.join(columns)}) "
                    f"VALUES({','.join('?' for _ in columns)})",
                    (claim.request_id, *identity.values()),
                )
        if cached is not None:
            verify()
            return cached

        metadata: dict[str, Any] = {
            "usage_status": "UNKNOWN",
            "provider_revision": None,
            "route": route,
        }
        sent = False

        def transport(event: dict[str, Any]) -> None:
            nonlocal sent
            if event["phase"] == "SEND_INTENT":
                verify()
                with self.db.connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    if claim.verify_transaction is not None:
                        claim.verify_transaction(db)
                    changed = db.execute(
                        "UPDATE generic_llm_calls SET status='SEND_INTENT' "
                        "WHERE id=? AND status='RESERVED'",
                        (claim.request_id,),
                    ).rowcount
                    if changed != 1:
                        raise ApiError(
                            409,
                            "MODEL_REQUEST_UNCERTAIN",
                            "The request cannot be resent.",
                        )
                sent = True
            elif event["phase"] in {"RESPONSE_COMPLETE", "RESPONSE_PARTIAL_RECEIPT"}:
                if event["phase"] == "RESPONSE_COMPLETE":
                    metadata["response_completion_observed"] = True
                response_id = event.get("provider_response_id")
                if isinstance(response_id, str) and 0 < len(response_id) <= 256:
                    metadata["provider_response_id"] = response_id
                metadata["native_reasoning_observed"] = (
                    event.get("native_reasoning_observed") is True
                )
                metadata["reasoning_effort_requested"] = event.get(
                    "reasoning_effort_requested"
                )
                metadata["returned_model"] = event.get("returned_model")
                usage = (event.get("input_tokens"), event.get("output_tokens"))
                if event.get("usage_reported") is True and all(
                    type(value) is int and value >= 0 for value in usage
                ):
                    metadata.update(
                        usage_status="REPORTED",
                        input_tokens=event.get("input_tokens"),
                        output_tokens=event.get("output_tokens"),
                    )
                if (
                    event["phase"] == "RESPONSE_COMPLETE"
                    and event.get("returned_model") != "qwen3.8-max"
                ):
                    raise ApiError(
                        502,
                        "MODEL_IDENTITY_MISMATCH",
                        "The service identity did not match.",
                    )

        try:
            output, run = self.provider.generate(
                schema,
                instructions=instructions,
                context=payload,
                role=role,
                template_version=template_version,
                schema_version=schema_version,
                max_output_tokens=max_output_tokens,
                transport_event_sink=transport,
                stream_checkpoint=verify,
            )
            if not sent or metadata.get("returned_model") != "qwen3.8-max":
                raise ApiError(
                    502,
                    "MODEL_IDENTITY_UNVERIFIED",
                    "The service response was not verified.",
                )
        except ProviderCallFailure as failure:
            metadata["error_class"] = type(failure.cause).__name__
            if isinstance(failure.cause, ApiError):
                metadata["error_code"] = failure.cause.code
            metadata["failure_receipt"] = {
                key: failure.run[key]
                for key in (
                    "status",
                    "error_class",
                    "failure_layer",
                    "http_status",
                    "timeout_kind",
                    "cause_chain",
                    "latency_ms",
                    "started_at",
                    "finished_at",
                    "response_received",
                    "max_output_tokens",
                    "timeouts",
                )
                if key in failure.run
            }
            outcome = failure.run.get("status", "UNKNOWN")
            if (
                isinstance(failure.cause, ValidationError)
                and metadata.get("response_completion_observed") is True
                and metadata.get("returned_model") == "qwen3.8-max"
            ):
                outcome = "FAILED"
                metadata["error_code"] = "MODEL_SCHEMA_REJECTED"
                metadata["schema_error_summary"] = schema_error_summary(
                    failure.cause,
                    schema=schema,
                )
            self._finish(claim, outcome, None, metadata)
            raise failure.cause from failure
        except Exception as error:
            metadata["error_class"] = type(error).__name__
            if isinstance(error, ApiError):
                metadata["error_code"] = error.code
            self._finish(claim, "UNKNOWN" if sent else "BLOCKED", None, metadata)
            raise
        try:
            verify()
        except ApiError:
            self._finish(claim, "CANCELLED", None, metadata)
            raise
        metadata["provider_response_id"] = run.get("provider_response_id")
        self._finish(claim, "COMPLETED", output.model_dump_json(), metadata)
        return output

    def _finish(
        self,
        claim: ModelCallClaim,
        status: str,
        output: str | None,
        metadata: dict[str, Any],
    ) -> None:
        with self.db.connect() as db:
            changed = db.execute(
                "UPDATE generic_llm_calls SET status=?,output_json=?,audit_json=?,input_tokens=?,"
                "output_tokens=?,finished_at=? WHERE id=? AND status IN ('RESERVED','SEND_INTENT')",
                (
                    status,
                    output,
                    json.dumps(metadata),
                    metadata.get("input_tokens"),
                    metadata.get("output_tokens"),
                    datetime.now(UTC).isoformat(),
                    claim.request_id,
                ),
            ).rowcount
            if changed != 1:
                raise ApiError(
                    409,
                    "MODEL_ANSWER_RECEIPT_CONFLICT",
                    "The answer receipt was not saved.",
                )
