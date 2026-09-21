"""Laya input compiler: no silent truncation, full provenance.

The reference ``ref_build_sequence`` / ``ref_render_options`` / ``ref_serialize_state``
below are transcribed verbatim from ``work/laya-recon/rl_common.py`` and used to
prove that the compiler's pre-flight ``input_ids``/``markers``/``input_tokens`` are
byte-identical to what the official algorithm produces.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.laya import (
    COMPILER_VERSION,
    BudgetConfig,
    CompilePolicy,
    InputTooLongError,
    InsufficientContextError,
    OfflineTokenizer,
    TemplateOption,
    build_evidence_window,
    build_hierarchical_template_decision,
    build_single_local_relation,
    compile_decision,
)
from app.laya import build_sequence as mirror_build_sequence

# --------------------------------------------------------------------------- #
# Independent reference transcription of the official algorithm
# --------------------------------------------------------------------------- #


def ref_serialize_state(state: Any) -> str:
    if isinstance(state, str):
        return state
    return json.dumps(state, ensure_ascii=False)


def ref_render_options(q: dict[str, Any]) -> list[str]:
    t, crit = q["t"], q.get("crit")
    if t == "choice":
        return [k if not v else f"{k}: {v}" for k, v in crit.items()]
    if t == "score":
        return [f"level {i}: {c}" for i, c in enumerate(crit)]
    crit = crit or {}
    return [
        "false: " + (crit.get("false") or "no, the statement does not hold"),
        "true: " + (crit.get("true") or "yes, the statement holds"),
    ]


def ref_build_sequence(
    tok: Any,
    state: Any,
    q: dict[str, Any],
    max_len: int,
    head_max_len: int,
    option_order: list[int] | None = None,
    truncate_left: bool = False,
) -> tuple[list[int], list[int]]:
    mask_tok = tok.mask_token
    opts = ref_render_options(q)
    order = option_order if option_order is not None else list(range(len(opts)))
    ins = str(q["ins"]).replace(mask_tok, " ")
    head_text = f"{q['t']} question: {ins}"
    head_ids = tok(head_text, add_special_tokens=False)["input_ids"]
    opt_ids = []
    for i in order:
        opt_ids.append(
            [tok.mask_token_id]
            + tok(" " + opts[i].replace(mask_tok, " "), add_special_tokens=False)["input_ids"][:48]
        )
    opt_budget = head_max_len - sum(len(o) for o in opt_ids)
    if opt_budget < 16:  # too many / too long options: shrink every option text evenly
        per = max(4, (head_max_len - 16) // max(1, len(opt_ids)))
        opt_ids = [o[:per] for o in opt_ids]
        opt_budget = head_max_len - sum(len(o) for o in opt_ids)
    head_ids = head_ids[: max(8, opt_budget)]
    ids = [tok.cls_token_id] + head_ids + [tok.sep_token_id]
    markers = []
    for o in opt_ids:
        markers.append(len(ids))
        ids.extend(o)
    ids.append(tok.sep_token_id)
    room = max(0, max_len - len(ids) - 1)
    st = tok(ref_serialize_state(state).replace(mask_tok, " "), add_special_tokens=False)[
        "input_ids"
    ]
    st = st[-room:] if truncate_left else st[:room]
    ids = ids + st + [tok.sep_token_id]
    return ids[:max_len], [m for m in markers if m < max_len]


def words(n: int) -> str:
    """n whitespace-separated pieces (each a single word)."""
    return " ".join(["w"] * n)


def make_q(t: str, ins: str, crit: Any) -> dict[str, Any]:
    return {"t": t, "ins": ins, "crit": crit}


# --------------------------------------------------------------------------- #
# The four silent-cut points, each refused (and each optionally allowed+marked)
# --------------------------------------------------------------------------- #


def test_option_48_token_cut_refused_by_default() -> None:
    with pytest.raises(InputTooLongError) as exc:
        compile_decision(
            primitive="choice",
            instructions="pick one",
            criteria={"a": "short", "b": words(49)},
            state="some state",
        )
    assert exc.value.kind == "option"
    assert exc.value.data["option_48_truncated"] == [False, True]


def test_option_48_token_cut_allowed_and_marked() -> None:
    decision = compile_decision(
        primitive="choice",
        instructions="pick one",
        criteria={"a": "short", "b": words(49)},
        state="some state",
        policy=CompilePolicy(truncate_options=True),
    )
    assert decision.provenance.truncated_options is True
    assert decision.provenance.options_complete is True
    assert decision.provenance.per_option_tokens[1] == 48  # cut from 49 -> 48


def test_opt_budget_recut_always_refused() -> None:
    criteria = {f"opt{i}": words(48) for i in range(6)}  # 6 * (mask+48) = 294 > 256
    with pytest.raises(InputTooLongError) as exc:
        compile_decision(primitive="choice", instructions="pick", criteria=criteria, state="s")
    assert exc.value.kind == "options"
    assert exc.value.data["opt_budget_pre_re_cut"] < 16
    assert exc.value.data["per"] >= 4
    # the re-cut is refused even when per-option truncation is allowed
    with pytest.raises(InputTooLongError) as exc2:
        compile_decision(
            primitive="choice",
            instructions="pick",
            criteria=criteria,
            state="s",
            policy=CompilePolicy(truncate_options=True),
        )
    assert exc2.value.kind == "options"


def test_head_truncation_refused_and_allowed() -> None:
    with pytest.raises(InputTooLongError) as exc:
        compile_decision(
            primitive="choice",
            instructions=words(300),
            criteria={"a": "x", "b": "y"},
            state="s",
        )
    assert exc.value.kind == "instructions"

    decision = compile_decision(
        primitive="choice",
        instructions=words(300),
        criteria={"a": "x", "b": "y"},
        state="s",
        policy=CompilePolicy(truncate_instructions=True),
    )
    assert decision.provenance.truncated_head is True


def test_state_room_truncation_refused_and_allowed() -> None:
    state = words(80)
    config = BudgetConfig(max_len=64, head_max_len=32)
    with pytest.raises(InputTooLongError) as exc:
        compile_decision(
            primitive="choice",
            instructions="pick",
            criteria={"a": "x", "b": "y"},
            state=state,
            config=config,
        )
    assert exc.value.kind == "state"

    decision = compile_decision(
        primitive="choice",
        instructions="pick",
        criteria={"a": "x", "b": "y"},
        state=state,
        config=config,
        policy=CompilePolicy(truncate_state=True),
    )
    assert decision.provenance.truncated_state is True
    assert decision.provenance.retained_state_chars < len(state)


def test_option_vanished_by_max_len_refused() -> None:
    # markers land at positions 1+64+1 ... far beyond max_len=20; options stay
    # under 48 text tokens so only the vanish path triggers.
    config = BudgetConfig(max_len=20, head_max_len=256)
    criteria = {f"opt{i}": words(45) for i in range(4)}
    with pytest.raises(InputTooLongError) as exc:
        compile_decision(
            primitive="choice",
            instructions="pick one",
            criteria=criteria,
            state="x",
            config=config,
        )
    assert exc.value.kind == "options"
    assert "vanish" in exc.value.detail


# --------------------------------------------------------------------------- #
# Refusal taxonomy: empty state, too many options, plan leak
# --------------------------------------------------------------------------- #


def test_empty_state_refused() -> None:
    with pytest.raises(InsufficientContextError) as exc:
        compile_decision(primitive="choice", instructions="p", criteria={"a": "x"}, state="")
    assert exc.value.kind == "state"


def test_too_many_flat_options_refused() -> None:
    criteria = {f"opt{i}": f"v{i}" for i in range(21)}
    with pytest.raises(InputTooLongError) as exc:
        compile_decision(primitive="choice", instructions="pick", criteria=criteria, state="s")
    assert exc.value.kind == "options"
    assert exc.value.data["option_count"] == 21


def test_plan_leak_refused_and_allowed() -> None:
    state = {"message": "hi", "plan": "do the next unit"}
    with pytest.raises(InsufficientContextError) as exc:
        compile_decision(primitive="choice", instructions="p", criteria={"a": "x"}, state=state)
    assert exc.value.kind == "plan"
    assert "plan" in exc.value.data["fields"]

    decision = compile_decision(
        primitive="choice",
        instructions="p",
        criteria={"a": "x"},
        state=state,
        policy=CompilePolicy(allow_plan_state=True),
    )
    assert decision.provenance.truncated_state is False


def test_nested_plan_leak_detected() -> None:
    state = {"message": "hi", "nested": {"answer_key": "42"}}
    with pytest.raises(InsufficientContextError) as exc:
        compile_decision(primitive="choice", instructions="p", criteria={"a": "x"}, state=state)
    assert exc.value.kind == "plan"
    assert "answer_key" in exc.value.data["fields"]


# --------------------------------------------------------------------------- #
# Hierarchical classification for the 14 professional templates
# --------------------------------------------------------------------------- #


def _fourteen_templates() -> list[TemplateOption]:
    domains = ["health", "engineering", "business"]
    templates: list[TemplateOption] = []
    for i in range(14):
        domain = domains[i % 3]
        templates.append(
            TemplateOption(
                id=f"tpl_{i:02d}",
                name=f"Template {i:02d}",
                domain=domain,
                description=f"Template number {i:02d}",
            )
        )
    return templates


def test_hierarchical_classification_never_flat() -> None:
    decision = build_hierarchical_template_decision(
        templates=_fourteen_templates(), state={"course_title": "Anatomy 101"}
    )
    assert decision.other_label == "OTHER"
    # stage 1: small candidate set of domains + OTHER
    assert decision.stage1.provenance.option_count == 4  # 3 domains + OTHER
    assert "OTHER" in decision.stage1.criteria
    # stage 2: templates within one domain + OTHER, never all 14 at once
    assert set(decision.stage2) == {"health", "engineering", "business"}
    for stage in decision.stage2.values():
        assert stage.provenance.option_count <= 6  # <=5 templates + OTHER
        assert stage.provenance.option_count < 14
        assert "OTHER" in stage.criteria
        assert stage.provenance.fit_by_construction is True


def test_flat_fourteen_template_text_refused() -> None:
    # The full 14-template text as one flat question triggers the re-cut refusal.
    templates = _fourteen_templates()
    criteria = {t.id: t.description + " " + words(20) for t in templates}
    with pytest.raises(InputTooLongError) as exc:
        compile_decision(
            primitive="choice",
            instructions="match the course to a template",
            criteria=criteria,
            state={"course_title": "Anatomy 101"},
        )
    assert exc.value.kind == "options"


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #


def test_single_local_relation_enforces_two_to_six_options() -> None:
    decision = build_single_local_relation(
        instructions="which holds",
        options={"a": "first", "b": "second", "c": "third"},
        state="text",
    )
    assert decision.provenance.option_count == 3
    assert decision.provenance.fit_by_construction is True

    with pytest.raises(InputTooLongError):
        build_single_local_relation(
            instructions="which",
            options={f"o{i}": f"v{i}" for i in range(7)},
            state="text",
        )
    with pytest.raises(InsufficientContextError):
        build_single_local_relation(instructions="which", options={"only": "one"}, state="text")


def test_single_local_relation_refuses_long_option() -> None:
    with pytest.raises(InputTooLongError) as exc:
        build_single_local_relation(
            instructions="which",
            options={"a": "x", "b": "y" * 200},
            state="text",
        )
    assert exc.value.kind == "option"


def test_evidence_window_keeps_must_keep_and_drops_extras() -> None:
    fields = {
        "question": "solve x",
        "conditions": "x > 0",
        "negations": "not y",
        "numbers": "3",
        "units": "kg",
        "notes": " ".join(["extra"] * 200),
        "context": " ".join(["more"] * 200),
    }
    window = build_evidence_window(fields=fields, state_budget_tokens=100)
    assert window.retained_fields == ("question", "conditions", "negations", "numbers", "units")
    assert window.dropped_fields == ("notes", "context")
    assert window.fit_by_construction is True
    assert window.retained_chars < window.total_chars


def test_evidence_window_refuses_if_must_keep_does_not_fit() -> None:
    with pytest.raises(InputTooLongError) as exc:
        build_evidence_window(
            fields={"question": " ".join(["q"] * 50)},
            state_budget_tokens=5,
        )
    assert exc.value.kind == "state"


# --------------------------------------------------------------------------- #
# Provenance
# --------------------------------------------------------------------------- #


def test_provenance_populated() -> None:
    decision = compile_decision(
        primitive="choice",
        instructions="pick one",
        criteria={"a": "first", "b": "second"},
        state={"message": "hello world"},
        decision_key="test.decision.v1",
    )
    prov = decision.provenance
    assert prov.input_tokens == len(decision.input_ids)
    assert prov.option_count == 2
    assert prov.options_complete is True
    assert prov.truncated_state is False
    assert prov.truncated_head is False
    assert prov.truncated_options is False
    assert prov.head_budget > 0
    assert prov.state_room > 0
    assert prov.retained_state_chars > 0
    assert len(prov.content_hash) == 64
    assert prov.compiler_version == COMPILER_VERSION
    assert prov.decision_key == "test.decision.v1"
    assert set(prov.as_dict()) >= {
        "content_hash",
        "input_tokens",
        "option_count",
        "per_option_tokens",
        "options_complete",
        "retained_state_chars",
        "truncated_state",
        "truncated_head",
        "truncated_options",
        "head_budget",
        "state_room",
        "compiler_version",
    }


def test_content_hash_is_deterministic_and_input_sensitive() -> None:
    kwargs = dict(
        primitive="choice",
        instructions="pick",
        criteria={"a": "x", "b": "y"},
        state={"message": "hi"},
        decision_key="k",
    )
    d1 = compile_decision(**kwargs)
    d2 = compile_decision(**kwargs)
    assert d1.provenance.content_hash == d2.provenance.content_hash
    d3 = compile_decision(**{**kwargs, "state": {"message": "other"}})
    assert d3.provenance.content_hash != d1.provenance.content_hash


# --------------------------------------------------------------------------- #
# Equality property: compiler == independent reference transcription
# --------------------------------------------------------------------------- #


def _fits_cases() -> list[tuple[Any, dict[str, Any], int, int, list[int] | None, bool]]:
    """(state, q, max_len, head_max_len, option_order, truncate_left) — all fit."""
    cases: list[tuple[Any, dict[str, Any], int, int, list[int] | None, bool]] = [
        ("hello", make_q("choice", "pick", {"a": "x", "b": "y"}), 1024, 256, None, False),
        ("text", make_q("choice", "which", {"a": "first", "b": "second", "c": "third"}),
         1024, 256, None, False),
        (
            {"message": "hi there"},
            make_q("choice", "choose", {"a": "1", "b": "2", "c": "3", "d": "4"}),
            1024,
            256,
            [1, 0, 3, 2],
            False,
        ),
        ("text", make_q("score", "rate", ["low", "mid", "high"]), 1024, 256, None, False),
        ({"doc": "abc"}, make_q("score", "how", ["a", "b", "c", "d", "e"]), 1024, 256, None, False),
        ("text", make_q("noul", "yes or no", None), 1024, 256, None, False),
        ("text", make_q("noul", "holds?", {"false": "no", "true": "yes"}), 1024, 256, None, False),
        ("text", make_q("choice", "pick", {"a": "x", "b": "y"}), 1024, 256, [1, 0], True),
        ("state words here", make_q("choice", "pick", {"a": "x", "b": "y", "c": "z"}), 512, 192,
         None, False),
        ("state", make_q("choice", "pick", {"a": "x", "b": "y"}), 64, 32, None, False),
    ]
    for n in (2, 3, 4, 6):
        cases.append(
            (
                {"topic": f"t{n}", "message": "m"},
                make_q("choice", "pick", {f"o{i}": f"value {i}" for i in range(n)}),
                1024,
                256,
                list(reversed(range(n))),
                False,
            )
        )
    return cases


def _truncating_cases() -> list[tuple[Any, dict[str, Any], int, int, list[int] | None, bool]]:
    """Cases that hit each silent-cut regime (used only against the raw mirror)."""
    long_option = {"a": "short", "b": words(49)}
    many_long = {f"opt{i}": words(48) for i in range(6)}
    return [
        ("s", make_q("choice", "pick", long_option), 1024, 256, None, False),  # 48-cut
        ("s", make_q("choice", "pick", many_long), 1024, 256, None, False),  # re-cut
        ("s", make_q("choice", words(300), {"a": "x", "b": "y"}), 1024, 256, None, False),  # head
        (words(80), make_q("choice", "pick", {"a": "x", "b": "y"}), 64, 32, None, False),  # state
        ("x", make_q("choice", "pick one", {f"opt{i}": words(48) for i in range(4)}), 20, 256,
         None, False),  # vanish
    ]


def test_mirror_matches_reference_on_all_cases() -> None:
    tok = OfflineTokenizer()
    for state, q, max_len, head_max_len, order, truncate_left in (
        _fits_cases() + _truncating_cases()
    ):
        got = mirror_build_sequence(tok, state, q, max_len, head_max_len, order, truncate_left)
        want = ref_build_sequence(tok, state, q, max_len, head_max_len, order, truncate_left)
        assert got == want


def test_compiler_equality_property() -> None:
    tok = OfflineTokenizer()
    for state, q, max_len, head_max_len, order, truncate_left in _fits_cases():
        decision = compile_decision(
            primitive=q["t"],
            instructions=q["ins"],
            criteria=q["crit"],
            state=state,
            tokenizer=tok,
            config=BudgetConfig(max_len=max_len, head_max_len=head_max_len),
            option_order=order,
            truncate_left=truncate_left,
        )
        ref_ids, ref_markers = ref_build_sequence(
            tok, state, q, max_len, head_max_len, order, truncate_left
        )
        assert decision.input_ids == ref_ids
        assert decision.markers == ref_markers
        assert decision.input_tokens == len(ref_ids)


def test_compiled_decision_as_dict_roundtrip() -> None:
    decision = compile_decision(
        primitive="choice",
        instructions="pick",
        criteria={"a": "x", "b": "y"},
        state="s",
    )
    payload = decision.as_dict()
    assert isinstance(payload["input_ids"], list)
    assert payload["qtype"] == 0
    assert payload["provenance"]["input_tokens"] == payload["input_tokens"]
