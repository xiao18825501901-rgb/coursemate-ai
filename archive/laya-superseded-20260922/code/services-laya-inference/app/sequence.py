"""Tokenizer-only sequence construction, faithful to the official Laya code.

These functions re-implement the authoritative ``work/laya-recon/rl_common.py``
functions with identical truncation logic (only the torch/numpy imports were
dropped and the type hints/string formatting modernized for py311), so the
anti-abuse token measurement uses the exact same rules the model applies.

* ``serialize_state``  -- how a state is flattened before tokenization.
* ``render_options``   -- option texts in label-index order.
* ``build_sequence``   -- the [CLS] ... [SEP] [MASK] opt ... [SEP] state [SEP] layout.

Nothing here imports torch, so the service validation path is fully testable
without a model download.
"""

from __future__ import annotations

import json


def serialize_state(state) -> str:
    if isinstance(state, str):
        return state
    return json.dumps(state, ensure_ascii=False)


def render_options(q: dict) -> list[str]:
    """Option texts in label-index order. Noul is always [false, true] so p[1] == noul."""
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


def build_sequence(
    tok,
    state,
    q: dict,
    max_len: int,
    head_max_len: int,
    option_order: list[int] | None = None,
    truncate_left: bool = False,
):
    """[CLS] <type> instructions [SEP] [MASK] opt0 [MASK] opt1 ... [SEP] state [SEP].

    Returns input_ids and the positions of the per-option [MASK] markers.
    """
    mask_tok = tok.mask_token
    opts = render_options(q)
    order = option_order if option_order is not None else list(range(len(opts)))
    ins = str(q["ins"]).replace(mask_tok, " ")
    head_ids = tok(f"{q['t']} question: {ins}", add_special_tokens=False)["input_ids"]
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
    st = tok(serialize_state(state).replace(mask_tok, " "), add_special_tokens=False)["input_ids"]
    st = st[-room:] if truncate_left else st[:room]
    ids = ids + st + [tok.sep_token_id]
    return ids[:max_len], [m for m in markers if m < max_len]
