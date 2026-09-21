"""Lightweight, user-initiated feedback triage for CourseMate.

This module records a feedback report and *only* a feedback report: there is no
passive scanning, nothing reads other messages, other users' data, or a whole
conversation to "find" problems.  If the user did not submit a report, this
module does nothing and spends zero Jev calls.

A submitted report is triaged in one batched Jev call — ``feedback.category.v1``
(Choice) and ``feedback.severity.v1`` (Score) are two independent questions asked
on the *same* state, so they share one transport call — and is then queued for a
human reviewer.  Jev is a suggestion only: it can never close a ticket, delete
feedback, change a mark, or ban/limit a user, and no such call exists on this
module.

Privacy rules (pinned by tests):

* the default stored payload is identifiers only — ``message_id``/``run_id``/
  ``course_id``/``model``/``template_version``/``app_version`` plus the reporter's
  scope; the free-text description and the question/answer body are stored only
  when ``attach_body`` is set, and a body without that flag is refused;
* no mood/personality/ability inference is ever asked for or recorded;
* there are no cross-user reads: the only inputs are the reporter's own
  identifiers and opt-in content;
* duplicates are related by ``report_key`` — a digest of the real object ids,
  versions and the authorization scope — never by scanning private text;
* the cache scope is genuinely owner-scoped and course-scoped (a server-derived
  ``owner_scope_hash`` + ``course_id``), so one user's cached judgement can never
  be reused for another and a receipt write can never fail on a NULL
  ``owner_scope_hash``.

Degradation: when Jev is unavailable or returns an invalid answer the report is
still accepted and queued with ``category=OTHER``, the middle severity and
``path=fallback:<reason>``.  A Jev failure never loses the user's report.

The only persistent side effect is the Jev receipt ledger
(``jev_decision_receipts``) — no grade, user, permission or coverage row is ever
touched, and no new table is required.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Final
from uuid import uuid4

from app.jev.catalog import Primitive, load_catalog
from app.jev.errors import JevError
from app.jev.gateway import Receipt
from app.jev.models import (
    CacheScope,
    JevAnswer,
    JevCall,
    JevQuestion,
    input_hash,
    owner_scope_hash,
)
from app.jev.service import SemanticDecisionService

CATEGORY_KEY: Final = "feedback.category.v1"
SEVERITY_KEY: Final = "feedback.severity.v1"

CATEGORIES: Final = (
    "ANSWER_WRONG",
    "CITATION_WRONG",
    "QUESTION_INCOMPLETE",
    "IMAGE_RECOGNITION",
    "GRADING_DISPUTE",
    "COURSE_CLASSIFICATION",
    "SERVICE_FAULT",
    "OTHER",
)

SEVERITY_LEVELS: Final = ("0", "1", "2")
FALLBACK_CATEGORY: Final = "OTHER"
FALLBACK_SEVERITY: Final = 1  # the middle level: a real defect with a workaround

CALLER_ROLE: Final = "feedback_triage"

# Content categories that route to the human content-review queue (deterministic,
# never an automatic action).
_CONTENT_CATEGORIES: Final = frozenset(
    {"ANSWER_WRONG", "CITATION_WRONG", "QUESTION_INCOMPLETE", "IMAGE_RECOGNITION",
     "COURSE_CLASSIFICATION"}
)

_FAILURE_OUTCOMES: Final = {
    "JEV_NOT_CONFIGURED": "not_configured",
    "JEV_TIMEOUT": "timeout",
    "JEV_UNAVAILABLE": "unavailable",
    "JEV_INVALID_RESPONSE": "invalid_response",
    "JEV_INVALID_REQUEST": "invalid_request",
}


class FeedbackValidationError(ValueError):
    """A report violates a schema/privacy rule (e.g. a body without the opt-in)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def suggested_queue(category: str, severity: int) -> str:
    """A deterministic *suggestion* of which human queue should review the report.

    This is routing metadata only — it never performs an action, closes a ticket,
    changes a mark or sanctions a user.
    """
    if severity == 2:
        return "priority"
    if category == "SERVICE_FAULT":
        return "service"
    if category == "GRADING_DISPUTE":
        return "grading"
    if category in _CONTENT_CATEGORIES:
        return "content"
    return "triage"


@dataclass(frozen=True)
class FeedbackReport:
    """One user-submitted report.

    The identifiers (``course_id``, ``message_id``, ``run_id``, ``model``,
    ``template_version``, ``app_version``) and the structured ``category_hint``/
    ``product_surface`` are the minimal payload.  The free-text/body fields
    (``report_text``, ``question_text``, ``answer_text``) are stored only when
    ``attach_body`` is True.
    """

    course_id: str
    message_id: str | None = None
    run_id: str | None = None
    model: str | None = None
    template_version: str | None = None
    app_version: str | None = None
    category_hint: str | None = None
    product_surface: str = "learn"
    report_text: str | None = None
    question_text: str | None = None
    answer_text: str | None = None
    attach_body: bool = False

    def body_fields(self) -> dict[str, str | None]:
        """The opt-in gated fields, present only when the user opted in."""
        if not self.attach_body:
            return {}
        return {
            "report_text": self.report_text,
            "question_text": self.question_text,
            "answer_text": self.answer_text,
        }

    def as_dict(self) -> dict[str, Any]:
        """The stored representation: identifiers first, body only on opt-in."""
        payload: dict[str, Any] = {
            "course_id": self.course_id,
            "message_id": self.message_id,
            "run_id": self.run_id,
            "model": self.model,
            "template_version": self.template_version,
            "app_version": self.app_version,
            "category_hint": self.category_hint,
            "product_surface": self.product_surface,
        }
        payload.update(self.body_fields())
        return payload


@dataclass
class FeedbackTriageResult:
    """The triage suggestion plus the queued report (one per submitted report)."""

    report_key: str
    owner_scope_hash: str
    course_id: str | None
    category: str
    severity: int
    suggested_queue: str
    path: str
    used_jev: bool
    jev_calls: int
    category_path: str
    severity_path: str
    category_receipt_id: str | None
    severity_receipt_id: str | None
    latency_ms: float | None
    confidence: float | None
    definition_version: str
    report: FeedbackReport

    def as_dict(self) -> dict[str, Any]:
        return {
            "report_key": self.report_key,
            "category": self.category,
            "severity": self.severity,
            "suggested_queue": self.suggested_queue,
            "path": self.path,
            "used_jev": self.used_jev,
            "jev_calls": self.jev_calls,
            "receipts": {
                "category": self.category_receipt_id,
                "severity": self.severity_receipt_id,
            },
            "latency_ms": self.latency_ms,
            "confidence": self.confidence,
            "definition_version": self.definition_version,
            "report": self.report.as_dict(),
        }


def build_feedback_scope(
    owner_user_id: str,
    authorization_scope: str,
    *,
    course_id: str | None = None,
    workspace_id: str | None = None,
    material_revision: str | None = None,
    node_id: str | None = None,
    spec_version: int | str | None = None,
) -> CacheScope:
    """Build the genuinely-scoped :class:`CacheScope` the gateway's receipt needs.

    ``owner_scope_hash`` is server-derived (``owner_user_id`` + ``authorization_scope``)
    and never client-supplied, so two owners can never share a cached judgement.
    """
    return CacheScope(
        owner_scope_hash=owner_scope_hash(owner_user_id, authorization_scope),
        course_id=course_id,
        workspace_id=workspace_id,
        material_revision=material_revision,
        node_id=node_id,
        spec_version=str(spec_version) if spec_version is not None else None,
    )


def report_key(report: FeedbackReport, scope_hash: str) -> str:
    """Stable dedup key from the real object ids + versions + authorization scope.

    The free-text description and the question/answer body are deliberately absent,
    so two reports about the same object are related without scanning private text.
    """
    payload = {
        "course_id": report.course_id,
        "message_id": report.message_id,
        "run_id": report.run_id,
        "model": report.model,
        "template_version": report.template_version,
        "app_version": report.app_version,
        "owner_scope_hash": scope_hash,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                   default=str).encode()
    ).hexdigest()


class FeedbackTriage:
    """The single entry point for user-initiated feedback triage."""

    def __init__(self, service: SemanticDecisionService | None) -> None:
        self.service = service
        # The human review queue: reports in submission order, never mutated by Jev.
        self.reports: list[FeedbackTriageResult] = []

    def summary(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for result in self.reports:
            counts[f"{result.category}::{result.path}"] = (
                counts.get(f"{result.category}::{result.path}", 0) + 1
            )
        return {
            "submitted": len(self.reports),
            "counts": counts,
            "reports": [result.as_dict() for result in self.reports],
        }

    def submit(
        self,
        report: FeedbackReport,
        *,
        owner_user_id: str,
        authorization_scope: str,
        workspace_id: str | None = None,
        material_revision: str | None = None,
        node_id: str | None = None,
        spec_version: int | str | None = None,
    ) -> FeedbackTriageResult:
        """Record and triage one user-submitted report.

        ``owner_user_id``/``authorization_scope`` scope the Jev receipt (server-derived,
        never client-supplied), and ``course_id`` is taken from the report itself so a
        receipt is always owner-scoped and course-scoped.
        """
        _require_opt_in(report)
        _require_valid_hint(report)
        scope = build_feedback_scope(
            owner_user_id,
            authorization_scope,
            course_id=report.course_id,
            workspace_id=workspace_id,
            material_revision=material_revision,
            node_id=node_id,
            spec_version=spec_version,
        )
        key = report_key(report, scope.owner_scope_hash or "")
        state = _build_state(report)
        result = self._triage(report, scope, state, key)
        self.reports.append(result)
        return result

    # ---------------------------------------------------------------- internals

    def _version(self) -> str:
        if self.service is not None:
            return self.service.catalog.version
        return load_catalog().version

    def _triage(
        self,
        report: FeedbackReport,
        scope: CacheScope,
        state: dict[str, Any],
        key: str,
    ) -> FeedbackTriageResult:
        if self.service is None:
            return self._degraded(report, scope, key, "no_service", None)

        gateway = self.service.gateway
        catalog = gateway.catalog
        category_def = catalog.get(CATEGORY_KEY)
        severity_def = catalog.get(SEVERITY_KEY)
        category_mode = gateway.mode_for(CATEGORY_KEY)
        severity_mode = gateway.mode_for(SEVERITY_KEY)

        questions = _build_questions(category_def, severity_def, category_mode, severity_mode)
        if not questions:
            return self._degraded(report, scope, key, "off", None)

        call = JevCall(state=state, questions=questions)
        started = perf_counter()
        try:
            result = gateway.transport.call(
                call, timeout_seconds=gateway.bounds.timeout_seconds
            )
        except JevError as exc:
            latency_ms = (perf_counter() - started) * 1000
            return self._failed(
                report, scope, state, key, exc.code, latency_ms,
                category_def, severity_def, category_mode, severity_mode,
            )
        except Exception as exc:  # noqa: BLE001 - unknown transport failure fails closed
            latency_ms = (perf_counter() - started) * 1000
            return self._failed(
                report, scope, state, key, type(exc).__name__, latency_ms,
                category_def, severity_def, category_mode, severity_mode,
            )
        latency_ms = (perf_counter() - started) * 1000
        model_version = result.model_version

        category, category_path, category_used, category_confidence = _resolve_category(
            category_mode, result.answers.get(CATEGORY_KEY)
        )
        severity, severity_path, severity_used, severity_confidence = _resolve_severity(
            severity_mode, result.answers.get(SEVERITY_KEY)
        )

        category_receipt_id = self._record_receipt(
            category_def, scope, category_mode, state, result.answers.get(CATEGORY_KEY),
            latency_ms, model_version,
        )
        severity_receipt_id = self._record_receipt(
            severity_def, scope, severity_mode, state, result.answers.get(SEVERITY_KEY),
            latency_ms, model_version,
        )

        used_jev = category_used and severity_used
        path = "jev" if used_jev else _overall_path(category_path, severity_path)
        confidence = category_confidence if category_confidence is not None else severity_confidence
        return FeedbackTriageResult(
            report_key=key,
            owner_scope_hash=scope.owner_scope_hash or "",
            course_id=scope.course_id,
            category=category,
            severity=severity,
            suggested_queue=suggested_queue(category, severity),
            path=path,
            used_jev=used_jev,
            jev_calls=1,
            category_path=category_path,
            severity_path=severity_path,
            category_receipt_id=category_receipt_id,
            severity_receipt_id=severity_receipt_id,
            latency_ms=round(latency_ms, 3),
            confidence=confidence,
            definition_version=self._version(),
            report=report,
        )

    def _failed(
        self,
        report: FeedbackReport,
        scope: CacheScope,
        state: dict[str, Any],
        key: str,
        error_code: str,
        latency_ms: float,
        category_def: Any,
        severity_def: Any,
        category_mode: str,
        severity_mode: str,
    ) -> FeedbackTriageResult:
        outcome = _FAILURE_OUTCOMES.get(error_code, "unavailable")
        category_receipt_id = (
            self._record_receipt(category_def, scope, category_mode, state, None,
                                 latency_ms, None)
            if category_mode != "off"
            else None
        )
        severity_receipt_id = (
            self._record_receipt(severity_def, scope, severity_mode, state, None,
                                 latency_ms, None)
            if severity_mode != "off"
            else None
        )
        return self._degraded(
            report, scope, key, outcome, round(latency_ms, 3),
            category_receipt_id=category_receipt_id,
            severity_receipt_id=severity_receipt_id,
        )

    def _degraded(
        self,
        report: FeedbackReport,
        scope: CacheScope,
        key: str,
        reason: str,
        latency_ms: float | None,
        *,
        category_receipt_id: str | None = None,
        severity_receipt_id: str | None = None,
    ) -> FeedbackTriageResult:
        category = FALLBACK_CATEGORY
        severity = FALLBACK_SEVERITY
        return FeedbackTriageResult(
            report_key=key,
            owner_scope_hash=scope.owner_scope_hash or "",
            course_id=scope.course_id,
            category=category,
            severity=severity,
            suggested_queue=suggested_queue(category, severity),
            path=f"fallback:{reason}",
            used_jev=False,
            jev_calls=0,
            category_path=f"fallback:{reason}",
            severity_path=f"fallback:{reason}",
            category_receipt_id=category_receipt_id,
            severity_receipt_id=severity_receipt_id,
            latency_ms=latency_ms,
            confidence=None,
            definition_version=self._version(),
            report=report,
        )

    def _record_receipt(
        self,
        definition: Any,
        scope: CacheScope,
        mode: str,
        state: dict[str, Any],
        answer: JevAnswer | None,
        latency_ms: float,
        model_version: str | None,
    ) -> str | None:
        service = self.service
        if service is None:
            return None
        store = service.gateway.receipt_store
        if store is None:
            return None
        outcome = "ok" if answer is not None else "invalid_response"
        digest = input_hash(definition.key, state)
        receipt = Receipt(
            id=f"jev_{uuid4().hex}",
            definition_key=definition.key,
            primitive=definition.primitive,
            mode=mode,
            caller_role=CALLER_ROLE,
            owner_scope_hash=scope.owner_scope_hash,
            course_id=scope.course_id,
            workspace_id=scope.workspace_id,
            material_revision=scope.material_revision,
            node_id=scope.node_id,
            spec_version=scope.spec_version,
            question_hash=scope.question_hash,
            input_hash=digest,
            output_json=json.dumps(
                _suggestion_payload(definition, answer, outcome, model_version),
                ensure_ascii=False, sort_keys=True, default=str,
            ),
            outcome=outcome,
            latency_ms=round(latency_ms, 3),
            model_version=model_version,
        )
        store.save(receipt)
        return receipt.id


def _require_opt_in(report: FeedbackReport) -> None:
    if report.attach_body:
        return
    if any((report.report_text, report.question_text, report.answer_text)):
        raise FeedbackValidationError(
            "BODY_NOT_OPTED_IN",
            "The report text and question/answer body require the attach_body opt-in flag.",
        )


def _require_valid_hint(report: FeedbackReport) -> None:
    if report.category_hint is not None and report.category_hint not in CATEGORIES:
        raise FeedbackValidationError(
            "INVALID_CATEGORY",
            f"category_hint must be one of {CATEGORIES}, got {report.category_hint!r}.",
        )


def _build_state(report: FeedbackReport) -> dict[str, Any]:
    attached = [cid for cid in (report.message_id, report.run_id, report.course_id) if cid]
    return {
        "report_text": report.report_text or "",
        "attached_context_ids": attached,
        "product_surface": report.product_surface,
        "submitted_category": report.category_hint,
    }


def _build_questions(
    category_def: Any,
    severity_def: Any,
    category_mode: str,
    severity_mode: str,
) -> dict[str, JevQuestion]:
    questions: dict[str, JevQuestion] = {}
    if category_mode != "off":
        questions[CATEGORY_KEY] = JevQuestion(
            key=CATEGORY_KEY,
            primitive=Primitive.CHOICE,
            instructions=category_def.instructions,
            criteria=dict(category_def.criteria),
        )
    if severity_mode != "off":
        questions[SEVERITY_KEY] = JevQuestion(
            key=SEVERITY_KEY,
            primitive=Primitive.SCORE,
            instructions=severity_def.instructions,
            criteria=[severity_def.criteria[level] for level in severity_def.score_levels],
        )
    return questions


def _resolve_category(
    mode: str, answer: JevAnswer | None
) -> tuple[str, str, bool, float | None]:
    if mode == "off":
        return (FALLBACK_CATEGORY, "fallback:off", False, None)
    if mode == "on" and answer is not None and answer.choice in CATEGORIES:
        return (answer.choice, "jev", True, _confidence(answer))
    if mode == "shadow":
        return (FALLBACK_CATEGORY, "fallback:shadow", False, None)
    return (FALLBACK_CATEGORY, "fallback:invalid_response", False, None)


def _resolve_severity(
    mode: str, answer: JevAnswer | None
) -> tuple[int, str, bool, float | None]:
    if mode == "off":
        return (FALLBACK_SEVERITY, "fallback:off", False, None)
    if mode == "on" and answer is not None and answer.score in SEVERITY_LEVELS:
        return (int(answer.score), "jev", True, _confidence(answer))
    if mode == "shadow":
        return (FALLBACK_SEVERITY, "fallback:shadow", False, None)
    return (FALLBACK_SEVERITY, "fallback:invalid_response", False, None)


def _confidence(answer: JevAnswer | None) -> float | None:
    if answer is None:
        return None
    value = (answer.raw or {}).get("confidence")
    if value is None:
        return None
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def _overall_path(category_path: str, severity_path: str) -> str:
    if category_path == "jev" and severity_path == "jev":
        return "jev"
    if category_path != "jev":
        return category_path
    return severity_path


def _suggestion_payload(
    definition: Any,
    answer: JevAnswer | None,
    outcome: str,
    model_version: str | None,
) -> dict[str, Any]:
    if answer is None:
        return {"outcome": outcome, "model_version": model_version}
    if definition.primitive == Primitive.CHOICE:
        return {"choice": answer.choice, "model_version": model_version}
    return {"score": answer.score, "model_version": model_version}


def submit_feedback(
    service: SemanticDecisionService | None,
    report: FeedbackReport,
    *,
    owner_user_id: str,
    authorization_scope: str,
    workspace_id: str | None = None,
    material_revision: str | None = None,
    node_id: str | None = None,
    spec_version: int | str | None = None,
) -> FeedbackTriageResult:
    """Module-level convenience wrapper over :meth:`FeedbackTriage.submit`."""
    return FeedbackTriage(service).submit(
        report,
        owner_user_id=owner_user_id,
        authorization_scope=authorization_scope,
        workspace_id=workspace_id,
        material_revision=material_revision,
        node_id=node_id,
        spec_version=spec_version,
    )


__all__ = [
    "CATEGORIES",
    "CATEGORY_KEY",
    "FALLBACK_CATEGORY",
    "FALLBACK_SEVERITY",
    "SEVERITY_KEY",
    "SEVERITY_LEVELS",
    "FeedbackReport",
    "FeedbackTriage",
    "FeedbackTriageResult",
    "FeedbackValidationError",
    "build_feedback_scope",
    "report_key",
    "suggested_queue",
    "submit_feedback",
]
