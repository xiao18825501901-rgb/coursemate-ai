"""Model loader + warmup, and the small model interface the engine depends on.

The engine and the HTTP layer only ever talk to :class:`DecisionModel`. Two
implementations exist:

* :class:`LayaModel`  -- the real loader. It lazily imports torch/laya/transformers
  (so the rest of the service is importable and testable with no torch present),
  sets the thread budget, loads the ONE resident multilingual checkpoint, and
  warms it up with a lightweight inference.
* :class:`FakeModel`  -- a deterministic in-process stand-in used by the tests
  and the local smoke test. No torch, no network, no model download.

The answer shape passed through by ``predict`` is exactly the Laya
``system_one``/``predict`` contract (``{"model", "answers", "usage"}``); the
service does not invent a different answer schema.
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from app.schema import ModelRevisionInfo
from app.sequence import build_sequence, render_options, serialize_state
from app.settings import Settings

# Verified from work/laya-recon/ml_encoder_config.json (the multilingual encoder).
_KNOWN_MMBERT_VOCAB_SIZE = 256_000
_KNOWN_MMBERT_ENCODER = "jhu-clsp/mmBERT-base"

# Public model-identity type (shared with the /model-info and decision envelope).
ModelInfo = ModelRevisionInfo


@dataclass(frozen=True)
class TokenDiagnostics:
    total_tokens: int
    per_question_tokens: dict[str, int]
    state_tokens: int
    max_len: int
    head_max_len: int
    options_not_fit: tuple[str, ...]
    truncated: bool


@runtime_checkable
class DecisionModel(Protocol):
    def load(self) -> None: ...

    def warmup(self) -> None: ...

    @property
    def ready(self) -> bool: ...

    def predict(self, state: Any, questions: dict[str, Any]) -> dict[str, Any]: ...

    def token_diagnostics(self, state: Any, questions: dict[str, Any]) -> TokenDiagnostics: ...

    def model_info(self) -> ModelInfo: ...


def _confidence_from_probs(p: list[float], k: int) -> float:
    """1 - normalized entropy (mirrors confidence_from_probs in rl_common.py)."""
    if k < 2:
        return 1.0
    p = [max(1e-12, float(x)) for x in p[:k]]
    total = sum(p) or 1.0
    p = [x / total for x in p]
    ent = -sum(x * math.log(x) for x in p)
    return float(1 - ent / math.log(k))


def _stable_logits(seed_text: str, k: int) -> list[float]:
    """Deterministic pseudo-logits from a string hash (for the fake model only)."""
    h = 2166136261
    for ch in seed_text:
        h = (h ^ ord(ch)) * 16777619
        h &= 0xFFFFFFFF
    return [((h >> (i % 24)) & 0xFFFF) / 65535.0 for i in range(k)]


class FakeModel:
    """Deterministic stand-in. All knobs are injectable for tests."""

    def __init__(
        self,
        *,
        predict_fn: Callable[[Any, dict[str, Any]], dict[str, Any]] | None = None,
        token_fn: Callable[[Any, dict[str, Any]], TokenDiagnostics] | None = None,
        load_fn: Callable[[], None] | None = None,
        info: ModelInfo | None = None,
    ) -> None:
        self._predict_fn = predict_fn
        self._token_fn = token_fn
        self._load_fn = load_fn
        self._ready = False
        self._warm = False
        self._info = info or ModelInfo(
            model_name="laya-multilingual-fake",
            model_revision="fake",
            sdk_version="fake",
            tokenizer_revision="fake",
            encoder="fake",
            max_len=1024,
            head_max_len=256,
            vocab_size=None,
            backend="fake",
        )

    @property
    def ready(self) -> bool:
        return self._ready and self._warm

    def load(self) -> None:
        if self._load_fn is not None:
            self._load_fn()
        self._ready = True

    def warmup(self) -> None:
        # Lightweight warmup inference through the same predict path.
        self.predict({"warmup": True}, {"warmup": {"type": "noul", "instructions": "warmup"}})
        self._warm = True

    def predict(self, state: Any, questions: dict[str, Any]) -> dict[str, Any]:
        if self._predict_fn is not None:
            return self._predict_fn(state, questions)
        return self._default_predict(state, questions)

    def token_diagnostics(self, state: Any, questions: dict[str, Any]) -> TokenDiagnostics:
        if self._token_fn is not None:
            return self._token_fn(state, questions)
        # Cheap deterministic proxy: ~4 chars per token, mirroring the real shape.
        state_text = serialize_state(state)
        state_tokens = max(1, len(state_text) // 4)
        per_question: dict[str, int] = {}
        for qid, q in questions.items():
            opts = render_options(_question_internal(q))
            per_question[qid] = max(4, (len(state_text) + sum(len(o) for o in opts)) // 4)
        return TokenDiagnostics(
            total_tokens=sum(per_question.values()),
            per_question_tokens=per_question,
            state_tokens=state_tokens,
            max_len=1024,
            head_max_len=256,
            options_not_fit=(),
            truncated=False,
        )

    def model_info(self) -> ModelInfo:
        return self._info

    @staticmethod
    def _default_predict(state: Any, questions: dict[str, Any]) -> dict[str, Any]:
        answers: dict[str, Any] = {}
        n_tokens = 0
        state_text = serialize_state(state)
        for qid, q in questions.items():
            q = _question_internal(q)
            t = q["t"]
            opts = render_options(q)
            k = len(opts)
            logits = _stable_logits(f"{state_text}|{qid}", max(k, 2))
            mx = max(logits) if logits else 0.0
            ex = [math.exp(z - mx) for z in logits[:k]]
            s = sum(ex) or 1.0
            p = [v / s for v in ex]
            ext = {"act_probability": 0.5}
            if t == "choice":
                keys = list(q["crit"].keys())
                answers[qid] = {
                    "type": "choice",
                    "choice": keys[int(max(range(k), key=lambda i: p[i]))],
                    "probabilities": {
                        kk: round(float(v), 4) for kk, v in zip(keys, p, strict=True)
                    },
                    "confidence": round(_confidence_from_probs(p, k), 4),
                    "rl_agent": ext,
                }
            elif t == "score":
                answers[qid] = {
                    "type": "score",
                    "score": round(float(sum(i * p[i] for i in range(k))), 4),
                    "legend": {str(i): c for i, c in enumerate(q["crit"])},
                    "probabilities": {str(i): round(float(v), 4) for i, v in enumerate(p)},
                    "confidence": round(_confidence_from_probs(p, k), 4),
                    "rl_agent": ext,
                }
            else:
                answers[qid] = {"type": "noul", "noul": round(float(p[1]), 4), "rl_agent": ext}
            n_tokens += max(4, len(state_text) // 4)
        return {
            "model": "rl-agent",
            "answers": answers,
            "usage": {"input_tokens": n_tokens, "output_tokens": 0},
        }


def _question_internal(q: dict[str, Any]) -> dict[str, Any]:
    """Normalise a Pydantic Question (or plain dict) into the Laya internal shape."""
    t = q["type"]
    crit = q.get("criteria")
    if t == "choice" and isinstance(crit, list):
        crit = {c: None for c in crit}
    instructions = q["instructions"]
    return {
        "t": t,
        "ins": instructions if isinstance(instructions, str) else json.dumps(instructions),
        "crit": crit,
    }


class LayaModel:
    """Real loader for the resident multilingual checkpoint (lazy, offline)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._agent: Any = None
        self._tokenizer: Any = None
        self._ready = False
        self._warm = False
        self._load_error: str | None = None
        self._info: ModelInfo | None = None

    @property
    def ready(self) -> bool:
        return self._ready and self._warm

    @property
    def load_error(self) -> str | None:
        return self._load_error

    def load(self) -> None:
        settings = self._settings
        if settings.offline:
            os.environ["HF_HUB_OFFLINE"] = "1"
        # Thread budget BEFORE any model construction (see runbook rationale).
        import torch  # lazy: torch is absent in the test/fake environment

        torch.set_num_threads(settings.torch_threads)
        torch.set_num_interop_threads(settings.torch_interop_threads)

        import laya  # lazy: the SDK is absent in the test/fake environment

        model_dir = settings.model_dir
        if model_dir is not None:
            # The pinned snapshot is a snapshot of the WHOLE repo, whose root also
            # holds the English checkpoint (`encoder/`, `tokenizer/`,
            # `rl_agent_config.json`). Loading the root would silently serve the
            # English model for Chinese material — explicitly forbidden — so the
            # multilingual subfolder is always selected here.
            subfolder_dir = model_dir / settings.model_subfolder
            if not (subfolder_dir / "rl_agent_config.json").is_file():
                raise FileNotFoundError(
                    f"{subfolder_dir} is not a Laya checkpoint: "
                    f"{settings.model_subfolder}/rl_agent_config.json is missing"
                )
            agent = laya.load(str(model_dir), subfolder=settings.model_subfolder)
        else:  # pragma: no cover - real backend requires model_dir (see Settings)
            agent = laya.load(settings.model_repo, subfolder=settings.model_subfolder)

        self._agent = agent
        # Independent tokenizer for the anti-abuse token measurement. It must be the
        # SUBFOLDER tokenizer (mmBERT-base, 256k vocab): the repository root ships a
        # different (English) tokenizer, and counting with it would misjudge every
        # limit. Loaded once at startup so request-time counting needs no further I/O.
        tokenizer_dir = (
            model_dir / settings.model_subfolder / "tokenizer" if model_dir is not None else None
        )
        if tokenizer_dir is not None:
            if not tokenizer_dir.is_dir():
                raise FileNotFoundError(f"{tokenizer_dir} is missing from the snapshot")
            from transformers import AutoTokenizer  # lazy

            self._tokenizer = AutoTokenizer.from_pretrained(str(tokenizer_dir))
        self._ready = True
        self._info = self._build_info()

    def warmup(self) -> None:
        self.predict({"warmup": True}, {"warmup": {"type": "noul", "instructions": "warmup"}})
        self._warm = True

    def predict(self, state: Any, questions: dict[str, Any]) -> dict[str, Any]:
        if self._agent is None:
            raise RuntimeError("model not loaded")
        # The SDK exposes predict(state, questions); the recon RLAgent exposes
        # system_one(state, questions). Both return the identical contract.
        fn = getattr(self._agent, "predict", None) or getattr(self._agent, "system_one", None)
        if fn is None:
            raise RuntimeError("loaded agent exposes neither predict() nor system_one()")
        return fn(state, questions)

    def token_diagnostics(self, state: Any, questions: dict[str, Any]) -> TokenDiagnostics:
        tok = self._tokenizer
        max_len = self._settings.max_len
        head_max_len = self._settings.head_max_len
        state_text = serialize_state(state)
        state_tokens = (
            len(tok(state_text.replace(tok.mask_token, " "), add_special_tokens=False)["input_ids"])
            if tok is not None
            else max(1, len(state_text) // 4)
        )
        per_question: dict[str, int] = {}
        options_not_fit: list[str] = []
        truncated = False
        for qid, q in questions.items():
            internal = _question_internal(q)
            n_options = len(render_options(internal))
            if tok is not None:
                ids, markers = build_sequence(tok, state_text, internal, max_len, head_max_len)
                per_question[qid] = len(ids)
                if len(markers) != n_options:
                    options_not_fit.append(qid)
                if len(ids) == max_len:
                    truncated = True
            else:  # pragma: no cover - tokenizer should exist for the real model
                per_question[qid] = max(4, len(state_text) // 4)
        return TokenDiagnostics(
            total_tokens=sum(per_question.values()),
            per_question_tokens=per_question,
            state_tokens=state_tokens,
            max_len=max_len,
            head_max_len=head_max_len,
            options_not_fit=tuple(options_not_fit),
            truncated=truncated,
        )

    def model_info(self) -> ModelInfo:
        if self._info is not None:
            return self._info
        return self._build_info()

    def _build_info(self) -> ModelInfo:
        settings = self._settings
        vocab = _KNOWN_MMBERT_VOCAB_SIZE
        if self._tokenizer is not None:
            try:
                vocab = int(self._tokenizer.vocab_size or vocab)
            except (AttributeError, TypeError, ValueError):  # pragma: no cover
                vocab = _KNOWN_MMBERT_VOCAB_SIZE
        sdk_version = "unknown"
        try:
            from importlib.metadata import version

            sdk_version = version("laya")
        except Exception:  # pragma: no cover - package may not expose metadata
            sdk_version = "unknown"
        revision = self._resolve_revision()
        return ModelInfo(
            model_name="laya-multilingual",
            model_revision=revision,
            sdk_version=sdk_version,
            tokenizer_revision="unknown",
            encoder=_KNOWN_MMBERT_ENCODER,
            max_len=settings.max_len,
            head_max_len=settings.head_max_len,
            vocab_size=vocab,
            backend="real",
        )

    def _resolve_revision(self) -> str:
        """Prefer the manifest revision (what actually landed); else the pin."""
        model_dir = self._settings.model_dir
        manifest = model_dir / "model-manifest.json" if model_dir is not None else None
        if manifest is not None and manifest.exists():
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
                rev = data.get("revision")
                if isinstance(rev, str) and rev:
                    return rev
            except (OSError, ValueError):  # pragma: no cover
                pass
        return self._settings.model_revision


def build_model(settings: Settings) -> DecisionModel:
    """Construct (not load) the model object. Loading happens on the load thread."""
    if settings.model_backend == "fake":
        return FakeModel()
    return LayaModel(settings)
