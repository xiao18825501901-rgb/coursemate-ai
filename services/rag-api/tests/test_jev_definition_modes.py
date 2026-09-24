"""Promotion is now possible, and that is all this setting does.

The shipped service could only ever run the catalogue's default, which is `shadow` for every
definition: a definition could be *measured* but never promoted, so nothing could promote one and no
deployment could show that a promotion changes behaviour. `JEV_DEFINITION_MODES` supplies the modes.

The tests below pin both halves of the intent: the default keeps every definition in shadow (an
empty setting must behave exactly as before), and a value that names something unknown **refuses**
rather than being ignored — a silently dropped promotion is indistinguishable from a promotion that
had no effect, which is the mistake this setting could most easily hide.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.jev.catalog import load_catalog
from app.jev.gateway import MODES, DecisionRequest, JevGateway, JevRequestError
from app.jev.models import CacheScope, JevAnswer, JevResult


def _settings(**overrides) -> Settings:
    base = dict(
        database_path=":memory:",
        app_env="test",
        rag_provider_mode="deterministic",
        v3_enabled=True,
    )
    base.update(overrides)
    return Settings(**base)


def test_the_default_is_empty_so_nothing_is_promoted() -> None:
    assert _settings().jev_definition_modes == ""
    assert _settings().jev_definition_mode_map == {}


def test_a_definition_can_be_promoted_by_name() -> None:
    settings = _settings(jev_definition_modes="retrieval.support.v1=on")
    assert settings.jev_definition_mode_map == {"retrieval.support.v1": "on"}


def test_several_definitions_and_spacing_are_handled() -> None:
    settings = _settings(
        jev_definition_modes=" retrieval.support.v1 = ON , pedagogy.next_method.v1=shadow "
    )
    assert settings.jev_definition_mode_map == {
        "retrieval.support.v1": "on",
        "pedagogy.next_method.v1": "shadow",
    }


def test_an_unknown_definition_refuses_instead_of_being_ignored() -> None:
    settings = _settings(jev_definition_modes="retrieval.support.v2=on")
    with pytest.raises(ValueError) as raised:
        _ = settings.jev_definition_mode_map
    assert "unknown definition" in str(raised.value)


def test_an_unknown_mode_refuses() -> None:
    settings = _settings(jev_definition_modes="retrieval.support.v1=advisory")
    with pytest.raises(ValueError) as raised:
        _ = settings.jev_definition_mode_map
    assert "not one of" in str(raised.value)


def test_a_malformed_pair_refuses() -> None:
    settings = _settings(jev_definition_modes="retrieval.support.v1")
    with pytest.raises(ValueError) as raised:
        _ = settings.jev_definition_mode_map
    assert "key=mode" in str(raised.value)


def test_every_catalog_definition_is_a_valid_key() -> None:
    """The validation authority is the catalogue, so every registered key must pass it."""
    catalog = load_catalog()
    pairs = ",".join(f"{key}=shadow" for key in catalog.definitions)
    settings = _settings(jev_definition_modes=pairs)
    assert set(settings.jev_definition_mode_map) == set(catalog.definitions)


def test_the_gateway_and_the_config_refuse_the_same_modes() -> None:
    """One vocabulary: a mode the config accepts must be one the gateway accepts, and vice versa."""
    assert sorted(MODES) == ["off", "on", "shadow"]
    gateway = JevGateway(modes={"retrieval.support.v1": "advisory"})
    with pytest.raises(JevRequestError):
        gateway.mode_for("retrieval.support.v1")
    for mode in sorted(MODES):
        promoted = JevGateway(modes={"retrieval.support.v1": mode})
        assert promoted.mode_for("retrieval.support.v1") == mode


def test_a_promoted_definition_is_actually_used_and_a_shadowed_one_is_not() -> None:
    """The property a browser acceptance needs: promotion changes `used`, shadow does not.

    This is what makes the promotion observable at all — `used` is False in shadow *whether or not a
    credential exists*, which is why the browser suite as written cannot tell a live Jev from an
    absent one (see the round-86 note in `DSH_JEV_DEEPSEEK_EXECUTION_STATE.md`).
    """
    from app.jev.service import SemanticDecisionService

    class FixedTransport:
        """Answers every question it is asked, keyed by the question's own key."""

        def call(self, call, *, timeout_seconds: float) -> JevResult:  # noqa: ANN001
            key = next(iter(call.questions))
            return JevResult(answers={key: JevAnswer(choice="CONTINUE")}, model_version="fixed")

    catalog = load_catalog()
    definition = catalog.get("intent.next_action.v1")
    scope = CacheScope(owner_scope_hash="o", course_id="c")

    def evaluate(modes: dict[str, str]):
        service = SemanticDecisionService(JevGateway(transport=FixedTransport(), modes=modes))
        request = DecisionRequest(
            definition=definition,
            state={
                "message": "keep going",
                "fixed_anchor": "n",
                "current_mode": "learning",
                "active_assessment": "none",
            },
            caller_role="test",
            criteria=dict(definition.criteria or {}),
            cache_scope=scope,
        )
        return service._decide(request, deterministic=None)  # noqa: SLF001

    shadowed = evaluate({})
    promoted = evaluate({"intent.next_action.v1": "on"})

    assert shadowed.used_jev is False, "shadow must never be used"
    assert promoted.used_jev is True, "a promoted definition must actually be used"
    assert promoted.value == "CONTINUE"
    assert promoted.path == "jev"
    assert shadowed.path.startswith("fallback:")
