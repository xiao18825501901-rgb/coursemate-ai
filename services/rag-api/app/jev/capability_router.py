"""TeachingCapabilityRouter: code-filtered, Jev-selected routing to a CourseMate capability.

"Capability" here means CourseMate's **own** teaching capabilities (``direct_qa``,
``node_lesson``, … ``assessment_submission``) — never DSH plugins, never arbitrary
internet code. The router sits in front of the existing handlers/orchestrator entry
points and answers one question: *which of the legal teaching capabilities should
serve this learner request?*

Two stages, and Jev only ever runs the second::

    stage 1 (deterministic, zero Jev): filter the nine capabilities down to the
        survivors that are legal for this request — permissions, product mode, the
        already-routed explicit command, normal-vs-Thinking, revealed answer state,
        the active assessment state, the current Pair binding and the server's own
        candidate list.  Jev is never offered an illegal candidate.
    stage 2 (optional, at most one disambiguation round): offer the surviving
        candidate list (capped) to ``teaching.capability.v1`` and let Jev select one
        candidate or ``NO_SKILL``.  Only the selected candidate's detail object is
        then looked up from the in-code catalog; the full templates are never sent.

Hard invariants (enforced by the filters, never delegated to Jev):

* a ``normal`` request can never be routed to a Thinking-only capability;
* a hidden-answer capability is excluded while the answer is unrevealed;
* an assessment-state precondition is enforced in code;
* Jev may never turn a Normal request into Thinking, raise the reasoning strength,
  reveal a hidden answer, re-enable a disabled entry point, change the Pair/node
  binding, or skip the current legal assessment state — those are all represented
  as filter conditions here, so a Jev answer can only choose among survivors;
* an illegal candidate proposed by the transport is rejected (the gateway validates
  against the offered criteria, and the router re-checks the id before acting);
* ``NO_SKILL``/unavailable always falls back to the current legal default capability
  (``direct_qa`` unless the caller overrides it) — never an empty tool call, never a
  stuck site.

The result of :meth:`TeachingCapabilityRouter.resolve` is a
:class:`CapabilityResolution` carrying the selected :class:`Capability` object, its
handler entry-point name and the recorded path, so the business layer can actually
call the existing orchestrator entry — a receipt alone is not integration.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from app.jev.catalog import load_catalog
from app.jev.gateway import DecisionRequest
from app.jev.models import CacheScope, owner_scope_hash
from app.jev.service import SemanticDecisionService

TEACHING_CAPABILITY_KEY: Final = "teaching.capability.v1"
NO_SKILL: Final = "NO_SKILL"
DEFAULT_SKILL: Final = "direct_qa"

# Owner bounds: never offer more than this many candidates to Jev, and never spend
# more than one disambiguation round on top of the initial selection.
MAX_OFFERED_CANDIDATES: Final = 4
MAX_DISAMBIGUATION_ROUNDS: Final = 1

_PERMISSION_PREFIX: Final = "permission:"

# Explicit teaching commands already resolved by
# ``app.learning.intent_commands.route_explicit_command``.  Only the actions that
# denote a teaching capability are mapped; PAUSE/OTHER are not a capability and fall
# through to the normal filter path.
_EXPLICIT_COMMAND_SKILL: Final = {
    "CONTINUE": "node_lesson",
    "ANSWER_AND_RESUME": "node_lesson",
    "ANSWER_ONLY": "direct_qa",
    "QUIZ_WAIT": "exercise",
    "SUBMIT_ASSESSMENT": "assessment_submission",
}

_NO_SKILL_DESCRIPTION: Final = "No offered capability is legal or clearly intended"

_DISAMBIGUATION_INSTRUCTION: Final = (
    "The learner request is ambiguous between the offered capabilities. Choose exactly "
    "one of them, or NO_SKILL if none clearly applies."
)


def build_capability_scope(
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
    and never client-supplied, so two owners can never share a cached judgement, and a
    private scope can never hash the same as a public one.
    """
    return CacheScope(
        owner_scope_hash=owner_scope_hash(owner_user_id, authorization_scope),
        course_id=course_id,
        workspace_id=workspace_id,
        material_revision=material_revision,
        node_id=node_id,
        spec_version=str(spec_version) if spec_version is not None else None,
    )


@dataclass(frozen=True)
class Capability:
    """One in-code capability catalog entry (the nine CourseMate capabilities)."""

    skill_id: str
    version: str
    description: str
    allowed_modes: tuple[str, ...]  # product modes the capability may serve
    preconditions: tuple[str, ...]  # permission tags + state requirements
    required_inputs: tuple[str, ...]  # inputs the mapped handler needs (documentation)
    writes_data: bool
    cost_class: str  # "read" | "generate" | "write"
    forbidden_conditions: tuple[str, ...]  # state conditions that exclude the skill
    handler: str  # existing handler/orchestrator entry point the skill maps to


@dataclass(frozen=True)
class CapabilityRequest:
    """The authoritative, server-derived inputs for one capability decision."""

    learner_request: str
    product_mode: str
    revealed_state: bool
    active_assessment: str | None
    pair_binding: str | None
    candidate_skills: tuple[str, ...] = ()
    mode: str = "normal"  # "normal" | "thinking"
    permissions: frozenset[str] = frozenset()
    explicit_command: str | None = None
    enabled_skills: frozenset[str] | None = None  # None => all catalog skills enabled
    default_skill: str = DEFAULT_SKILL


@dataclass(frozen=True)
class CapabilityResolution:
    """The selected capability, its handler name and the recorded decision path."""

    skill_id: str
    capability: Capability | None
    handler: str
    path: str  # "jev" | "jev:disambiguated" | "deterministic:*" | "fallback:*"
    used_jev: bool = False
    receipt_id: str | None = None
    offered_candidates: tuple[str, ...] = ()
    disambiguation_rounds: int = 0
    jev_calls: int = 0
    fallback_reason: str | None = None


CAPABILITY_CATALOG: dict[str, Capability] = {
    capability.skill_id: capability
    for capability in (
        Capability(
            skill_id="direct_qa",
            version="1.0.0-design",
            description="Answer the learner's question directly with grounded retrieval + citation",
            allowed_modes=("qa", "teach"),
            preconditions=(),
            required_inputs=("question", "course_context"),
            writes_data=False,
            cost_class="read",
            forbidden_conditions=("assessment_active",),
            handler="app.services.qa.QaService.stream",
        ),
        Capability(
            skill_id="node_lesson",
            version="1.0.0-design",
            description="Teach (or continue teaching) the bound knowledge node/unit",
            allowed_modes=("teach",),
            preconditions=("permission:teach", "pair_bound"),
            required_inputs=("node_id", "workspace"),
            writes_data=True,
            cost_class="write",
            forbidden_conditions=("assessment_active",),
            handler="app.learning.orchestrator.LearningOrchestrator.teach",
        ),
        Capability(
            skill_id="prerequisite_explanation",
            version="1.0.0-design",
            description="Explain/repair a missing prerequisite before advancing",
            allowed_modes=("teach",),
            preconditions=("permission:teach",),
            required_inputs=("current_node", "error"),
            writes_data=False,
            cost_class="read",
            forbidden_conditions=("assessment_active",),
            handler="app.learning.knowledge.KnowledgeService.select_repair_prerequisite",
        ),
        Capability(
            skill_id="worked_example",
            version="1.0.0-design",
            description="Present a complete worked example (Thinking-tier pedagogy)",
            allowed_modes=("teach",),
            preconditions=("permission:teach",),
            required_inputs=("topic", "current_step"),
            writes_data=False,
            cost_class="generate",
            forbidden_conditions=("thinking_only", "assessment_active"),
            handler="app.jev.callsites.select_pedagogy_method (WORKED_EXAMPLE)",
        ),
        Capability(
            skill_id="code_trace",
            version="1.0.0-design",
            description="Walk a concrete state/code trace (Thinking-tier pedagogy)",
            allowed_modes=("teach",),
            preconditions=("permission:teach",),
            required_inputs=("topic", "current_step"),
            writes_data=False,
            cost_class="generate",
            forbidden_conditions=("thinking_only", "assessment_active"),
            handler="app.jev.callsites.select_pedagogy_method (TRACE)",
        ),
        Capability(
            skill_id="figure_explanation",
            version="1.0.0-design",
            description="Explain a figure/attachment in the course material",
            allowed_modes=("teach", "qa"),
            preconditions=(),
            required_inputs=("figure_reference",),
            writes_data=False,
            cost_class="generate",
            forbidden_conditions=("assessment_active",),
            handler="app.ui_extension.domain.V3DomainAdapter figure/attachment explanation path",
        ),
        Capability(
            skill_id="exercise",
            version="1.0.0-design",
            description="Generate an independent exercise for the current node",
            allowed_modes=("teach", "exercise"),
            preconditions=("permission:exercise", "pair_bound"),
            required_inputs=("node_id",),
            writes_data=True,
            cost_class="write",
            forbidden_conditions=("assessment_active",),
            handler="app.cm_update.app.generate_exercise_run",
        ),
        Capability(
            skill_id="step_explanation",
            version="1.0.0-design",
            description="Explain one step of an already-revealed answer",
            allowed_modes=("teach", "exercise"),
            preconditions=("revealed",),
            required_inputs=("exercise_id", "step_id"),
            writes_data=True,
            cost_class="write",
            forbidden_conditions=("answer_unrevealed",),
            handler="app.cm_update.app step-explanation endpoints (cmui_step_explanations)",
        ),
        Capability(
            skill_id="assessment_submission",
            version="1.0.0-design",
            description="Submit the active assessment (still requires the confirmed UI action)",
            allowed_modes=("assess",),
            preconditions=("permission:assess", "active_assessment"),
            required_inputs=("session_id", "answers"),
            writes_data=True,
            cost_class="write",
            forbidden_conditions=("assessment_inactive",),
            handler="app.learning.orchestrator.LearningOrchestrator.submit_assessment",
        ),
    )
}


def _permission_tag(precondition: str) -> str | None:
    if precondition.startswith(_PERMISSION_PREFIX):
        return precondition[len(_PERMISSION_PREFIX):]
    return None


def filter_candidates(
    request: CapabilityRequest, catalog: dict[str, Capability] | None = None
) -> tuple[str, ...]:
    """Stage 1: deterministic filters.  Only the survivors are ever offered to Jev.

    Order of checks (all in code, zero Jev calls):

    * the server's own ``candidate_skills`` hint narrows the universe;
    * a disabled entry point is never re-enabled;
    * ``product_mode`` must be in the capability's ``allowed_modes``;
    * a Thinking-only capability is forbidden for a ``normal`` request;
    * a hidden-answer capability is forbidden while the answer is unrevealed;
    * assessment-state preconditions/forbiddens are enforced;
    * permission preconditions must be satisfied by the actor's permissions.
    """
    catalog = catalog if catalog is not None else CAPABILITY_CATALOG
    skills = list(catalog)
    if request.candidate_skills:
        allowed = set(request.candidate_skills)
        skills = [skill_id for skill_id in skills if skill_id in allowed]

    survivors: list[str] = []
    for skill_id in skills:
        capability = catalog[skill_id]
        if request.enabled_skills is not None and skill_id not in request.enabled_skills:
            continue
        if request.product_mode not in capability.allowed_modes:
            continue
        if "thinking_only" in capability.forbidden_conditions and request.mode != "thinking":
            continue
        if "answer_unrevealed" in capability.forbidden_conditions and not request.revealed_state:
            continue
        if (
            "assessment_active" in capability.forbidden_conditions
            and request.active_assessment is not None
        ):
            continue
        if (
            "assessment_inactive" in capability.forbidden_conditions
            and request.active_assessment is None
        ):
            continue
        permitted = True
        for precondition in capability.preconditions:
            tag = _permission_tag(precondition)
            if tag is not None:
                if tag not in request.permissions:
                    permitted = False
                    break
                continue
            if precondition == "revealed" and not request.revealed_state:
                permitted = False
                break
            if precondition == "active_assessment" and request.active_assessment is None:
                permitted = False
                break
            if precondition == "pair_bound" and request.pair_binding is None:
                permitted = False
                break
        if not permitted:
            continue
        survivors.append(skill_id)
    return tuple(survivors)


def _narrow(survivors: Sequence[str], max_offered: int) -> tuple[str, ...]:
    """Cap the offered candidate list (catalog order) so the full set is never sent."""
    return tuple(survivors[:max_offered])


class TeachingCapabilityRouter:
    """The single entry point for teaching-capability routing."""

    def __init__(
        self,
        service: SemanticDecisionService | None,
        *,
        catalog: dict[str, Capability] | None = None,
        max_offered: int = MAX_OFFERED_CANDIDATES,
        max_disambiguation_rounds: int = MAX_DISAMBIGUATION_ROUNDS,
    ) -> None:
        self.service = service
        self.catalog = dict(catalog) if catalog is not None else CAPABILITY_CATALOG
        self.max_offered = max_offered
        self.max_disambiguation_rounds = max_disambiguation_rounds

    def resolve(
        self,
        request: CapabilityRequest,
        *,
        owner_user_id: str,
        authorization_scope: str,
        course_id: str | None = None,
        workspace_id: str | None = None,
        material_revision: str | None = None,
        node_id: str | None = None,
        spec_version: int | str | None = None,
    ) -> CapabilityResolution:
        """Resolve the request to one capability (or the legal default), usable by the caller.

        The cache scope is built here from the server-derived owner/authorization/course
        values and passed to the gateway, so a Jev call always writes a properly-scoped
        receipt (``owner_scope_hash`` is never NULL) and never reuses another owner's
        cached judgement.
        """
        scope = build_capability_scope(
            owner_user_id,
            authorization_scope,
            course_id=course_id,
            workspace_id=workspace_id,
            material_revision=material_revision,
            node_id=node_id,
            spec_version=spec_version,
        )

        # 1. Explicit command already handled by intent_commands: route it with zero
        #    Jev calls, still honouring the hard invariants.
        if request.explicit_command is not None:
            skill_id = _EXPLICIT_COMMAND_SKILL.get(request.explicit_command)
            if skill_id is not None:
                if skill_id in self.catalog and skill_id in filter_candidates(
                    request, self.catalog
                ):
                    capability = self.catalog[skill_id]
                    return CapabilityResolution(
                        skill_id=skill_id,
                        capability=capability,
                        handler=capability.handler,
                        path="deterministic:explicit_command",
                    )
                return self._default(request, "explicit_command_forbidden")

        # 2. Stage 1: deterministic filters.
        survivors = filter_candidates(request, self.catalog)
        if not survivors:
            return self._default(request, "no_candidates")
        offered = _narrow(survivors, self.max_offered)

        # 3. Stage 2: Jev selection (skipped entirely when the layer is off).
        if self.service is None:
            return self._default(request, "no_service", offered=offered)

        choice, receipt_id, made = self._ask(request, offered, scope, disambiguating=False)
        jev_calls = 1 if made else 0
        if choice is not None:
            return self._selected(
                request, choice, path="jev", receipt_id=receipt_id,
                offered=offered, jev_calls=jev_calls,
            )

        # 4. At most one disambiguation round when the first answer was ambiguous.
        if self.max_disambiguation_rounds > 0 and len(offered) > 1:
            choice, receipt_id, made = self._ask(request, offered, scope, disambiguating=True)
            jev_calls += 1 if made else 0
            if choice is not None:
                return self._selected(
                    request, choice, path="jev:disambiguated", receipt_id=receipt_id,
                    offered=offered, jev_calls=jev_calls, rounds=1,
                )

        # 5. NO_SKILL / invalid / unavailable -> the current legal default.
        return self._default(
            request, "no_skill", offered=offered, jev_calls=jev_calls, receipt_id=receipt_id,
        )

    def _ask(
        self,
        request: CapabilityRequest,
        offered: tuple[str, ...],
        scope: CacheScope,
        *,
        disambiguating: bool,
    ) -> tuple[str | None, str | None, bool]:
        """Offer the short candidate list to Jev; return (choice, receipt_id, made_call).

        The choice is only ever one of the offered survivors: the gateway validates
        against the offered criteria, and this method re-checks the id before acting,
        so an illegal candidate proposed by the transport is rejected, never routed.
        """
        service = self.service
        if service is None:
            return (None, None, False)
        definition = load_catalog().get(TEACHING_CAPABILITY_KEY)
        criteria = {skill_id: self.catalog[skill_id].description for skill_id in offered}
        criteria[NO_SKILL] = _NO_SKILL_DESCRIPTION
        instructions = definition.instructions
        if disambiguating:
            instructions = f"{instructions} {_DISAMBIGUATION_INSTRUCTION}"
        state: dict[str, Any] = {
            "learner_request": request.learner_request,
            "product_mode": request.product_mode,
            "revealed_state": request.revealed_state,
            "active_assessment": request.active_assessment,
            "pair_binding": request.pair_binding,
            "candidate_skills": list(offered),
        }
        decision_request = DecisionRequest(
            definition=definition,
            state=state,
            caller_role="capability",
            cache_scope=scope,
            criteria=criteria,
            instructions=instructions,
        )
        decision = service.gateway.evaluate(decision_request)
        if (
            decision.mode == "on"
            and decision.suggestion is not None
            and decision.suggestion.choice in offered
        ):
            return (decision.suggestion.choice, decision.receipt_id, True)
        return (None, decision.receipt_id, True)

    def _selected(
        self,
        request: CapabilityRequest,
        skill_id: str,
        *,
        path: str,
        receipt_id: str | None,
        offered: tuple[str, ...],
        jev_calls: int,
        rounds: int = 0,
    ) -> CapabilityResolution:
        capability = self.catalog[skill_id]
        return CapabilityResolution(
            skill_id=skill_id,
            capability=capability,
            handler=capability.handler,
            path=path,
            used_jev=True,
            receipt_id=receipt_id,
            offered_candidates=offered,
            disambiguation_rounds=rounds,
            jev_calls=jev_calls,
        )

    def _default(
        self,
        request: CapabilityRequest,
        reason: str,
        *,
        offered: tuple[str, ...] = (),
        jev_calls: int = 0,
        receipt_id: str | None = None,
    ) -> CapabilityResolution:
        default_skill = request.default_skill
        capability = self.catalog.get(default_skill)
        return CapabilityResolution(
            skill_id=default_skill,
            capability=capability,
            handler=capability.handler if capability is not None else "",
            path=f"fallback:{reason}",
            used_jev=False,
            receipt_id=receipt_id,
            offered_candidates=offered,
            jev_calls=jev_calls,
            fallback_reason=reason,
        )


def resolve_capability(
    service: SemanticDecisionService | None,
    request: CapabilityRequest,
    *,
    owner_user_id: str,
    authorization_scope: str,
    course_id: str | None = None,
    workspace_id: str | None = None,
    material_revision: str | None = None,
    node_id: str | None = None,
    spec_version: int | str | None = None,
) -> CapabilityResolution:
    """Module-level convenience wrapper over :meth:`TeachingCapabilityRouter.resolve`."""
    return TeachingCapabilityRouter(service).resolve(
        request,
        owner_user_id=owner_user_id,
        authorization_scope=authorization_scope,
        course_id=course_id,
        workspace_id=workspace_id,
        material_revision=material_revision,
        node_id=node_id,
        spec_version=spec_version,
    )


__all__ = [
    "CAPABILITY_CATALOG",
    "Capability",
    "CapabilityRequest",
    "CapabilityResolution",
    "DEFAULT_SKILL",
    "MAX_DISAMBIGUATION_ROUNDS",
    "MAX_OFFERED_CANDIDATES",
    "NO_SKILL",
    "TEACHING_CAPABILITY_KEY",
    "TeachingCapabilityRouter",
    "build_capability_scope",
    "filter_candidates",
    "resolve_capability",
]
