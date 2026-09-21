"""Token-budget accounting for the Laya input compiler.

This module mirrors the official rendering/sequence logic verbatim from
``work/laya-recon/rl_common.py`` (``render_options``, ``serialize_state``,
``build_sequence``) so the compiler's pre-flight token counts are *identical* to
what the served checkpoint will encode. Tokenization is injected; the default is
a deterministic offline stand-in, never a network call and never ``transformers``
inside a test.

The four silent truncation points the official pipeline performs are:

1. per-option ``tok(" " + opt)[:48]`` (per-option silent truncation at 48 tokens);
2. ``opt_budget < 16`` -> every option re-cut to ``per`` tokens (labels collapse);
3. ``head_ids[:max(8, opt_budget)]`` (instructions silently truncated);
4. ``st[:room]`` (state silently truncated from the right).

``compute_budget_plan`` reproduces the exact final ``input_ids``/``markers`` while
recording, for each of the four points, whether content was actually cut. The
compiler uses those diagnostics to refuse before the call; it never reproduces a
silent cut.
"""

from __future__ import annotations

import json
import zlib
from dataclasses import dataclass
from typing import Any, Protocol

# --------------------------------------------------------------------------- #
# Documented special-token ids for mmBERT-base (ModernBERT multilingual), from
# work/laya-recon/ml_encoder_config.json: vocab_size 256000, pad 0, cls/sep/eos
# 1, mask 4. Text-token ids never affect the sequence *length*, which is the only
# thing the equality property asserts; they are deterministic and non-special so
# they can never collide with the documented ids.
# --------------------------------------------------------------------------- #
CLS_TOKEN_ID = 1
SEP_TOKEN_ID = 1
MASK_TOKEN_ID = 4
PAD_TOKEN_ID = 0
MASK_TOKEN = "<mask>"
VOCAB_SIZE = 256000
TEXT_ID_FLOOR = 5  # text ids start above every documented special id


class TokenizerProtocol(Protocol):
    """The tokenizer contract the compiler and its tests rely on.

    ``__call__(text, add_special_tokens=False)`` must return a mapping with an
    ``"input_ids"`` key. The special-token attributes below are the documented
    mmBERT-base ids; the served ``AutoTokenizer`` satisfies this contract.
    """

    mask_token: str
    mask_token_id: int
    cls_token_id: int
    sep_token_id: int
    pad_token_id: int

    def __call__(self, text: str, add_special_tokens: bool = False) -> dict[str, Any]: ...


def _pieces_and_spans(text: str) -> list[tuple[str, int, int]]:
    """Deterministic word/piece split: runs of letters/digits are one piece, every
    other character is its own piece, whitespace separates pieces. Returns
    ``(piece_text, char_start, char_end)`` with end-exclusive offsets aligned to
    ``__call__(text)["input_ids"]`` (so the compiler can map retained tokens back
    to a character count)."""
    out: list[tuple[str, int, int]] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch.isalnum():
            j = i
            while j < n and text[j].isalnum():
                j += 1
            out.append((text[i:j], i, j))
            i = j
        else:
            out.append((ch, i, i + 1))
            i += 1
    return out


class OfflineTokenizer:
    """Deterministic offline stand-in (no model, no network, no ``transformers``).

    A word/piece counter with the documented special-token ids. It reproduces the
    *length* of a real tokenization approximately and the special-token placement
    exactly; it is NOT the real mmBERT-base tokenizer and is never used to serve a
    checkpoint. ``spans`` gives char offsets so the compiler can report exact
    retained-state character counts.
    """

    mask_token = MASK_TOKEN
    mask_token_id = MASK_TOKEN_ID
    cls_token_id = CLS_TOKEN_ID
    sep_token_id = SEP_TOKEN_ID
    pad_token_id = PAD_TOKEN_ID

    def __call__(self, text: str, add_special_tokens: bool = False) -> dict[str, Any]:
        ids = [self._piece_id(p) for p, _s, _e in _pieces_and_spans(text)]
        if add_special_tokens:
            ids = [self.cls_token_id, *ids, self.sep_token_id]
        return {"input_ids": ids}

    def spans(self, text: str) -> list[tuple[int, int]]:
        """Char spans aligned to ``__call__(text)["input_ids"]`` (no specials)."""
        return [(start, end) for _p, start, end in _pieces_and_spans(text)]

    @staticmethod
    def _piece_id(piece: str) -> int:
        return TEXT_ID_FLOOR + (zlib.crc32(piece.encode("utf-8")) % (VOCAB_SIZE - TEXT_ID_FLOOR))


class AutoTokenizerAdapter:
    """Wraps ``transformers.AutoTokenizer``; only constructed when a model dir is present.

    The import is deferred inside ``__init__`` so that importing :mod:`app.laya.budget`
    (and therefore this whole package) in tests, or in a deployment without
    ``transformers``, has no side effects and makes no network call. A local
    ``model_dir`` is passed to ``AutoTokenizer.from_pretrained`` directly, so no
    Hub download is attempted.

    NOTE: not exercised by the test suite (the rag-api venv has no ``transformers``
    and no model directory). The adapter is documentation-plus-code for the
    production wiring; verify it against a real checkpoint before serving.
    """

    def __init__(self, model_dir: str) -> None:
        from transformers import AutoTokenizer  # deferred, local-only

        self._tok = AutoTokenizer.from_pretrained(model_dir)

    @property
    def mask_token(self) -> str:
        return str(self._tok.mask_token)

    @property
    def mask_token_id(self) -> int:
        return int(self._tok.mask_token_id)

    @property
    def cls_token_id(self) -> int:
        return int(self._tok.cls_token_id)

    @property
    def sep_token_id(self) -> int:
        return int(self._tok.sep_token_id)

    @property
    def pad_token_id(self) -> int:
        return int(self._tok.pad_token_id)

    def __call__(self, text: str, add_special_tokens: bool = False) -> dict[str, Any]:
        return self._tok(text, add_special_tokens=add_special_tokens)

    def spans(self, text: str) -> list[tuple[int, int]]:
        encoding = self._tok(text, add_special_tokens=False, return_offsets_mapping=True)
        return [(int(s), int(e)) for s, e in encoding.get("offset_mapping", [])]


# --------------------------------------------------------------------------- #
# Budget configuration
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class BudgetConfig:
    """Sequence budget. Defaults mirror ``ml_rl_agent_config.json`` (max_len 1024,
    head_max_len 256 for the multilingual mmBERT-base checkpoint)."""

    max_len: int = 1024
    head_max_len: int = 256

    @classmethod
    def from_ml_config(cls, data: dict[str, Any]) -> BudgetConfig:
        return cls(
            max_len=int(data.get("max_len", 1024)),
            head_max_len=int(data.get("head_max_len", 256)),
        )

    def state_budget_tokens(self) -> int:
        """Conservative state budget: the guaranteed minimum state room when the
        option+head section is maximally used (CLS/SEP overhead is >= 4 tokens)."""
        return max(0, self.max_len - self.head_max_len)


# --------------------------------------------------------------------------- #
# Faithful mirrors of the official rendering / sequence logic
# --------------------------------------------------------------------------- #
QTYPES = {"choice": 0, "score": 1, "noul": 2}


def serialize_state(state: Any) -> str:
    """Mirror of ``rl_common.serialize_state``."""
    if isinstance(state, str):
        return state
    return json.dumps(state, ensure_ascii=False)


def render_options(q: dict[str, Any]) -> list[str]:
    """Mirror of ``rl_common.render_options`` (option texts in label-index order)."""
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


@dataclass
class BudgetPlan:
    """The exact final sequence plus a diagnostic of every silent-cut point."""

    input_ids: list[int]
    markers: list[int]
    input_tokens: int
    option_count: int
    option_order: list[int]
    # instructions / head
    head_ids_full: list[int]
    head_ids_used: list[int]
    head_truncated: bool
    head_budget: int
    # options
    option_full_text_lengths: list[int]  # text tokens per option before the 48 cap
    option_used_lengths: list[int]  # final option id length per option (incl. mask)
    option_48_truncated: list[bool]
    opt_budget_pre_re_cut: int  # head_max_len - sum(48-capped options), the value that gates re-cut
    opt_budget: int  # post-re-cut budget (what head_budget is derived from)
    re_cut_triggered: bool
    per: int
    option_re_cut: list[bool]
    # state
    state_text: str
    state_full_length: int
    state_used_length: int
    state_truncated: bool
    state_room: int
    state_retained_chars: int
    # whole sequence
    options_vanish: list[bool]
    options_complete: bool


def _state_retained_chars(
    tok: Any, text: str, full_len: int, used_len: int, truncate_left: bool
) -> int:
    """Characters of ``text`` that survive after the room cut (exact via offsets)."""
    if used_len >= full_len:
        return len(text)
    spans_fn = getattr(tok, "spans", None)
    if spans_fn is None:
        return len(text)  # no char offsets available: report untruncated length
    try:
        spans = spans_fn(text)
    except Exception:
        return len(text)
    if not truncate_left:
        if used_len <= 0:
            return 0
        idx = min(used_len, len(spans)) - 1
        return spans[idx][1]
    if used_len <= 0:
        return len(text)
    idx = full_len - used_len
    if idx >= len(spans):
        return 0
    return len(text) - spans[idx][0]


def compute_budget_plan(
    tok: Any,
    state: Any,
    q: dict[str, Any],
    max_len: int,
    head_max_len: int,
    option_order: list[int] | None = None,
    truncate_left: bool = False,
) -> BudgetPlan:
    """Reproduce ``build_sequence`` exactly while recording every cut point."""
    mask_tok = tok.mask_token
    opts = render_options(q)
    order = list(option_order) if option_order is not None else list(range(len(opts)))
    ins = str(q["ins"]).replace(mask_tok, " ")
    head_text = f"{q['t']} question: {ins}"
    head_ids_full = list(tok(head_text, add_special_tokens=False)["input_ids"])

    opt_ids: list[list[int]] = []
    full_text_lengths: list[int] = []
    for i in order:
        text_ids = list(
            tok(" " + opts[i].replace(mask_tok, " "), add_special_tokens=False)["input_ids"]
        )
        full_text_lengths.append(len(text_ids))
        opt_ids.append([tok.mask_token_id] + text_ids[:48])

    opt_budget = head_max_len - sum(len(o) for o in opt_ids)
    opt_budget_pre_re_cut = opt_budget
    re_cut_triggered = opt_budget < 16
    per = 0
    option_re_cut = [False] * len(opt_ids)
    if re_cut_triggered:
        per = max(4, (head_max_len - 16) // max(1, len(opt_ids)))
        before = [len(o) for o in opt_ids]
        opt_ids = [o[:per] for o in opt_ids]
        option_re_cut = [len(o) < b for o, b in zip(opt_ids, before, strict=True)]
        opt_budget = head_max_len - sum(len(o) for o in opt_ids)

    head_budget = max(8, opt_budget)
    head_ids_used = head_ids_full[:head_budget]
    head_truncated = len(head_ids_full) > len(head_ids_used)

    ids = [tok.cls_token_id] + head_ids_used + [tok.sep_token_id]
    markers: list[int] = []
    for o in opt_ids:
        markers.append(len(ids))
        ids.extend(o)
    ids.append(tok.sep_token_id)

    room = max(0, max_len - len(ids) - 1)
    state_text = serialize_state(state).replace(mask_tok, " ")
    state_ids_full = list(tok(state_text, add_special_tokens=False)["input_ids"])
    state_ids_used = state_ids_full[-room:] if truncate_left else state_ids_full[:room]
    state_truncated = len(state_ids_full) > len(state_ids_used)

    ids = ids + state_ids_used + [tok.sep_token_id]
    final_ids = ids[:max_len]
    final_markers = [m for m in markers if m < max_len]
    options_vanish = [m >= max_len for m in markers]

    return BudgetPlan(
        input_ids=final_ids,
        markers=final_markers,
        input_tokens=len(final_ids),
        option_count=len(opts),
        option_order=order,
        head_ids_full=head_ids_full,
        head_ids_used=head_ids_used,
        head_truncated=head_truncated,
        head_budget=head_budget,
        option_full_text_lengths=full_text_lengths,
        option_used_lengths=[len(o) for o in opt_ids],
        option_48_truncated=[length > 48 for length in full_text_lengths],
        opt_budget_pre_re_cut=opt_budget_pre_re_cut,
        opt_budget=opt_budget,
        re_cut_triggered=re_cut_triggered,
        per=per,
        option_re_cut=option_re_cut,
        state_text=state_text,
        state_full_length=len(state_ids_full),
        state_used_length=len(state_ids_used),
        state_truncated=state_truncated,
        state_room=room,
        state_retained_chars=_state_retained_chars(
            tok, state_text, len(state_ids_full), len(state_ids_used), truncate_left
        ),
        options_vanish=options_vanish,
        options_complete=len(final_markers) == len(opts),
    )


def build_sequence(
    tok: Any,
    state: Any,
    q: dict[str, Any],
    max_len: int,
    head_max_len: int,
    option_order: list[int] | None = None,
    truncate_left: bool = False,
) -> tuple[list[int], list[int]]:
    """Faithful mirror of ``rl_common.build_sequence`` (single source of truth)."""
    plan = compute_budget_plan(tok, state, q, max_len, head_max_len, option_order, truncate_left)
    return plan.input_ids, plan.markers
