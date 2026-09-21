"""The Laya input compiler: no silent truncation, full provenance.

The official Laya pipeline shortens inputs in four places (per-option 48-token
cut, the ``opt_budget < 16`` re-cut, instruction/head cut, state ``room`` cut) and
additionally lets an option vanish entirely when ``max_len`` is reached. This
compiler detects every one of those *before* the call and either (a) fits the
request by construction — shortening only within documented per-field limits that
a builder controls, and marking that it did so — or (b) refuses with a typed error
handing the decision back to the deterministic/DeepSeek path.

It never emits a request whose options were silently re-cut to ``per`` tokens while
keeping their names, and never leaks a plan/hidden-answer field unless the caller
passes an explicit ``allow_plan_state`` guard.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from .budget import (
    QTYPES,
    BudgetConfig,
    OfflineTokenizer,
    TokenizerProtocol,
    compute_budget_plan,
)

COMPILER_VERSION = "laya-input-compiler/1.0.0"

_PRIMITIVE_ALIASES = {
    "choice": "choice",
    "score": "score",
    "noul": "noul",
    "Choice": "choice",
    "Score": "score",
    "Noul": "noul",
}

# --------------------------------------------------------------------------- #
# Documented state-key allowlist / plan-like deny-list
# --------------------------------------------------------------------------- #
# Union of ``required_state`` across the 12 catalog definitions (services/rag-api/
# app/jev/decision_catalog.json). The compiler refuses plan/hidden-answer keys by
# default; enforcing this full allowlist is opt-in (``enforce_state_allowlist``)
# because "dynamic" decisions legitimately carry server-generated ids under these
# keys rather than extra top-level keys.
ALLOWED_STATE_KEYS = frozenset(
    {
        "active_assessment",
        "allowed_predecessor_nodes",
        "candidate_answer_spans",
        "candidate_id",
        "candidate_spans",
        "candidate_text",
        "claim",
        "course_title",
        "current_mode",
        "current_node",
        "current_step",
        "current_task",
        "curriculum_samples",
        "deterministic_verification",
        "document_fragment",
        "eligible_prototypes",
        "error",
        "exact_target",
        "fixed_anchor",
        "frozen_question",
        "frozen_rubric_criterion",
        "known_course_level",
        "known_prior_evidence",
        "learner_request",
        "learning_evidence",
        "materials_revision",
        "message",
        "node",
        "node_spec_version",
        "parse_flags",
        "recent_exposures",
        "reference_solution",
        "remaining_scope",
        "required_item",
        "saved_delivery",
        "segment",
        "source_metadata",
        "source_span",
        "source_version",
        "student_answer",
        "task_scope",
        "template_profile",
        "topic",
        "valid_spans",
    }
)

# Exact (case-insensitive) keys that carry a plan or a hidden/expected answer. The
# compiler refuses any state containing one of these unless ``allow_plan_state``.
# Matching is exact on the key, so ``student_answer`` / ``reference_solution`` (the
# *authorized* inputs of assessment.criterion_review.v1) are not matched by
# ``answer`` / ``solution``.
PLAN_LIKE_STATE_KEYS = frozenset(
    {
        "plan",
        "plans",
        "lesson_plan",
        "teaching_plan",
        "tutor_plan",
        "answer",
        "answers",
        "answer_key",
        "answer_keys",
        "answer_sheet",
        "hidden_answer",
        "expected_answer",
        "model_answer",
        "gold_answer",
        "reference_answer",
        "correct_answer",
        "final_answer",
        "full_answer",
        "solution",
        "solutions",
        "solution_key",
        "model_solution",
        "next_steps",
        "next_actions",
        "planned_steps",
        "plan_steps",
        "grading_key",
        "marking_scheme",
    }
)


# --------------------------------------------------------------------------- #
# Typed errors
# --------------------------------------------------------------------------- #
class LayaCompileError(Exception):
    """Base class for every compiler refusal (a typed error, not a truncated call)."""

    code = "LAYA_COMPILE_ERROR"

    def __init__(self, kind: str, detail: str, *, data: dict[str, Any] | None = None) -> None:
        super().__init__(detail)
        self.kind = kind
        self.detail = detail
        self.data = data or {}

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": self.kind, "detail": self.detail, "data": self.data}


class InputTooLongError(LayaCompileError):
    """The instructions, an option, or the state would be cut by the official rules."""

    code = "LAYA_INPUT_TOO_LONG"


class InsufficientContextError(LayaCompileError):
    """The context is absent, empty, or forbidden (e.g. a plan/hidden-answer field)."""

    code = "LAYA_INSUFFICIENT_CONTEXT"


# --------------------------------------------------------------------------- #
# Policy
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CompilePolicy:
    """Compiler refusal/shortening policy. Defaults are strict: refuse, never
    silently truncate. Every ``truncate_*`` flag that is True lets the compiler
    apply the *official* cut and mark it in provenance — the compiler still never
    emits the ``opt_budget < 16`` re-cut (that is always a refusal)."""

    max_flat_options: int = 20  # refuse a flat question above this (Banking77 collapse)
    truncate_options: bool = False  # allow the per-option 48-token cap (marked)
    truncate_instructions: bool = False  # allow shortening instructions (marked)
    truncate_state: bool = False  # allow shortening state (marked)
    allow_plan_state: bool = False  # allow plan/hidden-answer keys in state
    enforce_state_allowlist: bool = False  # refuse state keys outside ALLOWED_STATE_KEYS

    def as_dict(self) -> dict[str, Any]:
        return {
            "max_flat_options": self.max_flat_options,
            "truncate_options": self.truncate_options,
            "truncate_instructions": self.truncate_instructions,
            "truncate_state": self.truncate_state,
            "allow_plan_state": self.allow_plan_state,
            "enforce_state_allowlist": self.enforce_state_allowlist,
        }


# --------------------------------------------------------------------------- #
# Provenance
# --------------------------------------------------------------------------- #
@dataclass
class Provenance:
    """Per-decision provenance: where the content came from and how much of it the
    exact sequence actually retained."""

    source_fragment_ids: tuple[str, ...] = ()
    char_ranges: tuple[tuple[int, int], ...] = ()  # (start, end) per fragment, 0-based
    page_ranges: tuple[tuple[int, int], ...] = ()  # (first, last) per fragment
    content_hash: str = ""
    input_tokens: int = 0
    option_count: int = 0
    per_option_tokens: tuple[int, ...] = ()  # text-token budget actually used per option
    options_complete: bool = True
    retained_state_chars: int = 0
    truncated_state: bool = False
    truncated_head: bool = False
    truncated_options: bool = False
    head_budget: int = 0  # max(8, opt_budget) actually applied to the head
    state_room: int = 0  # room actually applied to the state
    compiler_version: str = COMPILER_VERSION
    fit_by_construction: bool = False
    policy: dict[str, Any] = field(default_factory=dict)
    decision_key: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_fragment_ids": list(self.source_fragment_ids),
            "char_ranges": [list(r) for r in self.char_ranges],
            "page_ranges": [list(r) for r in self.page_ranges],
            "content_hash": self.content_hash,
            "input_tokens": self.input_tokens,
            "option_count": self.option_count,
            "per_option_tokens": list(self.per_option_tokens),
            "options_complete": self.options_complete,
            "retained_state_chars": self.retained_state_chars,
            "truncated_state": self.truncated_state,
            "truncated_head": self.truncated_head,
            "truncated_options": self.truncated_options,
            "head_budget": self.head_budget,
            "state_room": self.state_room,
            "compiler_version": self.compiler_version,
            "fit_by_construction": self.fit_by_construction,
            "policy": dict(self.policy),
            "decision_key": self.decision_key,
        }


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _canonical(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if isinstance(value, bool):
        return 1 if value else 0
    return value


def content_hash(
    decision_key: str, primitive: str, instructions: str, criteria: Any, state: Any
) -> str:
    """Stable digest of the exact inputs a decision is compiled from."""
    payload = json.dumps(
        _canonical(
            {
                "key": decision_key,
                "primitive": primitive,
                "instructions": instructions,
                "criteria": criteria,
                "state": state,
            }
        ),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Compiled decision
# --------------------------------------------------------------------------- #
@dataclass
class CompiledDecision:
    """A request ready to send, with the exact ``build_sequence`` layout so the
    compiler's pre-flight numbers equal the server's."""

    primitive: str  # "choice" | "score" | "noul"
    qtype: int  # QTYPES value (0/1/2)
    instructions: str
    criteria: dict[str, str] | list[str] | None
    input_ids: list[int]
    markers: list[int]
    input_tokens: int
    provenance: Provenance

    def as_dict(self) -> dict[str, Any]:
        return {
            "primitive": self.primitive,
            "qtype": self.qtype,
            "instructions": self.instructions,
            "criteria": self.criteria,
            "input_ids": list(self.input_ids),
            "markers": list(self.markers),
            "input_tokens": self.input_tokens,
            "provenance": self.provenance.as_dict(),
        }


# --------------------------------------------------------------------------- #
# Core compile
# --------------------------------------------------------------------------- #
def _plan_leak_keys(state: Any) -> list[str]:
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if str(key).lower() in PLAN_LIKE_STATE_KEYS:
                    found.append(str(key))
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(state)
    return found


def _option_count(primitive: str, criteria: Any) -> int:
    if primitive == "choice":
        return len(criteria) if isinstance(criteria, dict) else 0
    if primitive == "score":
        return len(criteria) if isinstance(criteria, list) else 0
    return 2  # noul is always [false, true]


def compile_decision(
    *,
    primitive: str,
    instructions: str,
    criteria: dict[str, str] | list[str] | None = None,
    state: dict[str, Any] | str,
    tokenizer: TokenizerProtocol | None = None,
    config: BudgetConfig | None = None,
    policy: CompilePolicy | None = None,
    provenance: Provenance | None = None,
    option_order: list[int] | None = None,
    truncate_left: bool = False,
    decision_key: str = "",
    fit_by_construction: bool = False,
) -> CompiledDecision:
    """Compile one decision to an exact ``build_sequence`` layout, or refuse.

    Raises :class:`InputTooLongError` / :class:`InsufficientContextError` before
    the call rather than reproducing any of the four silent cuts.
    """
    tok = tokenizer or OfflineTokenizer()
    cfg = config or BudgetConfig()
    pol = policy or CompilePolicy()

    t = _PRIMITIVE_ALIASES.get(primitive)
    if t is None:
        raise InsufficientContextError("primitive", f"unknown primitive {primitive!r}")

    # --- plan / hidden-answer leak (refuse unless explicitly allowed) ---------
    if isinstance(state, dict) and not pol.allow_plan_state:
        leak = _plan_leak_keys(state)
        if leak:
            raise InsufficientContextError(
                "plan",
                f"state contains plan/hidden-answer field(s): {', '.join(sorted(set(leak)))}",
                data={"fields": leak},
            )

    # --- empty state (no context to decide from) ------------------------------
    if state is None or (isinstance(state, str) and not state.strip()) or (
        isinstance(state, dict) and not state
    ):
        raise InsufficientContextError("state", "state is empty")

    # --- allowlist enforcement (opt-in) ---------------------------------------
    if pol.enforce_state_allowlist and isinstance(state, dict):
        extra = [str(k) for k in state if str(k).lower() not in ALLOWED_STATE_KEYS]
        if extra:
            raise InsufficientContextError(
                "state",
                f"state keys outside the documented allowlist: {', '.join(sorted(extra))}",
                data={"fields": extra},
            )

    option_count = _option_count(t, criteria)
    if option_count == 0:
        raise InsufficientContextError("options", f"primitive {t!r} has no options")
    if option_count > pol.max_flat_options:
        raise InputTooLongError(
            "options",
            f"flat question has {option_count} options (max {pol.max_flat_options}); "
            "split it, e.g. with build_hierarchical_template_decision",
            data={"option_count": option_count, "max_flat_options": pol.max_flat_options},
        )

    q: dict[str, Any] = {"t": t, "ins": instructions, "crit": criteria}
    plan = compute_budget_plan(
        tok, state, q, cfg.max_len, cfg.head_max_len, option_order, truncate_left
    )

    # --- the four silent-cut points, turned into refusals ---------------------
    if plan.re_cut_triggered:
        raise InputTooLongError(
            "options",
            "options do not fit in head_max_len: opt_budget < 16 forces every option "
            "to be re-cut to per-tokens while keeping its name (labels become "
            "indistinguishable); never emitted",
            data={
                "option_count": plan.option_count,
                "head_max_len": cfg.head_max_len,
                "opt_budget_pre_re_cut": plan.opt_budget_pre_re_cut,
                "per": plan.per,
            },
        )
    if any(plan.option_48_truncated) and not pol.truncate_options:
        raise InputTooLongError(
            "option",
            "an option exceeds 48 tokens and would be silently cut by the official rule; "
            "pass truncate_options=True to allow (it is still marked) or shorten the option",
            data={"option_48_truncated": plan.option_48_truncated},
        )
    if plan.head_truncated and not pol.truncate_instructions:
        raise InputTooLongError(
            "instructions",
            "instructions exceed the head budget and would be silently truncated; "
            "pass truncate_instructions=True to allow (it is still marked) or shorten them",
            data={
                "head_tokens": len(plan.head_ids_full),
                "head_budget": plan.head_budget,
            },
        )
    if not plan.options_complete:
        raise InputTooLongError(
            "options",
            "one or more options fall outside max_len and would vanish from the answer "
            "space; never emitted",
            data={"markers": plan.markers, "max_len": cfg.max_len},
        )
    if plan.state_truncated and not pol.truncate_state:
        raise InputTooLongError(
            "state",
            "state exceeds the remaining room and would be silently truncated from the "
            "right; pass truncate_state=True to allow (it is still marked), or use "
            "build_evidence_window to fit it by construction",
            data={
                "state_tokens": plan.state_full_length,
                "state_room": plan.state_room,
            },
        )

    src = provenance or Provenance()
    prov = Provenance(
        source_fragment_ids=src.source_fragment_ids,
        char_ranges=src.char_ranges,
        page_ranges=src.page_ranges,
        content_hash=src.content_hash
        or content_hash(decision_key, t, instructions, criteria, state),
        input_tokens=plan.input_tokens,
        option_count=plan.option_count,
        per_option_tokens=tuple(length - 1 for length in plan.option_used_lengths),
        options_complete=plan.options_complete,
        retained_state_chars=plan.state_retained_chars,
        truncated_state=plan.state_truncated,
        truncated_head=plan.head_truncated,
        truncated_options=any(plan.option_48_truncated) or any(plan.option_re_cut),
        head_budget=plan.head_budget,
        state_room=plan.state_room,
        compiler_version=COMPILER_VERSION,
        fit_by_construction=fit_by_construction,
        policy=pol.as_dict(),
        decision_key=decision_key,
    )

    return CompiledDecision(
        primitive=t,
        qtype=QTYPES[t],
        instructions=instructions,
        criteria=criteria,
        input_ids=plan.input_ids,
        markers=plan.markers,
        input_tokens=plan.input_tokens,
        provenance=prov,
    )


# --------------------------------------------------------------------------- #
# Builders (fit by construction)
# --------------------------------------------------------------------------- #
@dataclass
class EvidenceWindow:
    """A state window built by construction: must-keep fields survive verbatim,
    lower-priority fields are dropped (recorded, never silent)."""

    state: dict[str, Any]
    retained_fields: tuple[str, ...]
    dropped_fields: tuple[str, ...]
    retained_chars: int
    total_chars: int
    fit_by_construction: bool = True

    @property
    def text(self) -> str:
        return json.dumps(self.state, ensure_ascii=False)

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "retained_fields": list(self.retained_fields),
            "dropped_fields": list(self.dropped_fields),
            "retained_chars": self.retained_chars,
            "total_chars": self.total_chars,
            "fit_by_construction": self.fit_by_construction,
        }


def _tokens(tok: Any, text: str) -> int:
    return len(tok(text, add_special_tokens=False)["input_ids"])


def build_evidence_window(
    *,
    fields: dict[str, Any],
    must_keep: tuple[str, ...] = ("question", "conditions", "negations", "numbers", "units"),
    tokenizer: TokenizerProtocol | None = None,
    config: BudgetConfig | None = None,
    state_budget_tokens: int | None = None,
) -> EvidenceWindow:
    """Keep the current question, key conditions, negations, numbers and units
    inside the budget instead of dropping them. Extras are appended only while they
    fit; the rest are dropped and recorded. Refuses if a must-keep field alone does
    not fit (nothing is silently dropped)."""
    tok = tokenizer or OfflineTokenizer()
    cfg = config or BudgetConfig()
    budget = (
        state_budget_tokens
        if state_budget_tokens is not None
        else cfg.state_budget_tokens()
    )

    total_chars = len(json.dumps(fields, ensure_ascii=False))

    retained: dict[str, Any] = {}
    for key in must_keep:
        if key not in fields:
            continue
        candidate = dict(retained)
        candidate[key] = fields[key]
        if _tokens(tok, json.dumps(candidate, ensure_ascii=False)) > budget:
            raise InputTooLongError(
                "state",
                f"evidence window: must-keep field {key!r} alone does not fit in "
                f"{budget} state tokens",
                data={"field": key, "state_budget_tokens": budget},
            )
        retained[key] = fields[key]

    dropped: list[str] = []
    for key in [k for k in fields if k not in must_keep]:
        candidate = dict(retained)
        candidate[key] = fields[key]
        if _tokens(tok, json.dumps(candidate, ensure_ascii=False)) > budget:
            dropped.append(key)
        else:
            retained[key] = fields[key]

    text = json.dumps(retained, ensure_ascii=False)
    return EvidenceWindow(
        state=retained,
        retained_fields=tuple(retained),
        dropped_fields=tuple(dropped),
        retained_chars=len(text),
        total_chars=total_chars,
        fit_by_construction=True,
    )


def build_single_local_relation(
    *,
    instructions: str,
    options: dict[str, str] | list[str],
    state: dict[str, Any] | str,
    tokenizer: TokenizerProtocol | None = None,
    config: BudgetConfig | None = None,
    policy: CompilePolicy | None = None,
    provenance: Provenance | None = None,
    decision_key: str = "local_relation.v1",
    max_option_chars: int = 160,
    min_options: int = 2,
    max_options: int = 6,
) -> CompiledDecision:
    """One question, 2-6 concise options, fit by construction.

    Refuses options longer than ``max_option_chars`` rather than truncating them
    (the documented per-field character limit this builder controls)."""
    if isinstance(options, list):
        criteria: dict[str, str] = {str(i): opt for i, opt in enumerate(options)}
    else:
        criteria = dict(options)

    n = len(criteria)
    if n < min_options:
        raise InsufficientContextError(
            "options", f"single local relation needs {min_options}-{max_options} options, got {n}"
        )
    if n > max_options:
        raise InputTooLongError(
            "options", f"single local relation needs {min_options}-{max_options} options, got {n}"
        )

    for key, text in criteria.items():
        if len(text) > max_option_chars:
            raise InputTooLongError(
                "option",
                f"option {key!r} is {len(text)} chars, above this builder's "
                f"{max_option_chars}-char per-field limit",
                data={"option": key, "chars": len(text), "max_option_chars": max_option_chars},
            )

    return compile_decision(
        primitive="choice",
        instructions=instructions,
        criteria=criteria,
        state=state,
        tokenizer=tokenizer,
        config=config,
        policy=policy,
        provenance=provenance,
        decision_key=decision_key,
        fit_by_construction=True,
    )


@dataclass(frozen=True)
class TemplateOption:
    """One professional template: an id (returned by the model), a name/description
    the model sees, and the coarse domain/level it belongs to."""

    id: str
    name: str
    domain: str
    description: str = ""


@dataclass
class HierarchicalDecision:
    """Two-stage coarse-to-fine choice; "cannot decide" returns OTHER, never a
    forced match. Stage 1 picks the domain/level, stage 2 the template within it."""

    stage1: CompiledDecision
    stage2: dict[str, CompiledDecision]
    other_label: str = "OTHER"

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage1": self.stage1.as_dict(),
            "stage2": {domain: decision.as_dict() for domain, decision in self.stage2.items()},
            "other_label": self.other_label,
        }


def build_hierarchical_template_decision(
    *,
    templates: list[TemplateOption],
    state: dict[str, Any] | str,
    domain_instructions: str = "Which knowledge domain/level does this course require?",
    template_instructions: str = (
        "Which professional template best matches this course within {domain}?"
    ),
    tokenizer: TokenizerProtocol | None = None,
    config: BudgetConfig | None = None,
    policy: CompilePolicy | None = None,
    provenance: Provenance | None = None,
    decision_key: str = "template.match.v1",
    other_label: str = "OTHER",
) -> HierarchicalDecision:
    """Hierarchical classification helper for the professional templates.

    Never sends the whole template set as one flat question: stage 1 chooses a
    coarse domain/level from a small candidate set, stage 2 chooses the template
    within that domain. Both stages carry an OTHER option so "cannot decide"
    returns OTHER instead of forcing a choice."""
    if not templates:
        raise InsufficientContextError("templates", "no templates supplied for hierarchical match")

    domains = sorted({t.domain for t in templates})
    stage1_criteria: dict[str, str] = {domain: "" for domain in domains}
    stage1_criteria[other_label] = ""
    stage1 = compile_decision(
        primitive="choice",
        instructions=domain_instructions,
        criteria=stage1_criteria,
        state=state,
        tokenizer=tokenizer,
        config=config,
        policy=policy,
        provenance=provenance,
        decision_key=f"{decision_key}.domain",
        fit_by_construction=True,
    )

    stage2: dict[str, CompiledDecision] = {}
    for domain in domains:
        criteria = {t.id: (t.description or t.name) for t in templates if t.domain == domain}
        criteria[other_label] = ""
        stage2[domain] = compile_decision(
            primitive="choice",
            instructions=template_instructions.format(domain=domain),
            criteria=criteria,
            state=state,
            tokenizer=tokenizer,
            config=config,
            policy=policy,
            provenance=provenance,
            decision_key=f"{decision_key}.template.{domain}",
            fit_by_construction=True,
        )

    return HierarchicalDecision(stage1=stage1, stage2=stage2, other_label=other_label)
