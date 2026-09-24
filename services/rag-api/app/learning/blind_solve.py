"""Independent (blind) solve: the request builder that cannot see the author's answer.

The Question Engine's fifth stage solves the finished question in an **independent context** and
compares that solution with the author's. That comparison is only evidence if the two really were
independent, and independence here is not a property of the model or of the prompt wording — it is
a property of *what was sent*. Two calls to the same model are information isolation, never
statistical independence and never a second expert (the plan says so, and this module does not
pretend otherwise).

So the isolation is enforced where it can be checked: a **closed field whitelist**. The payload the
blind solver receives is built from `BLIND_SOLVE_FIELDS` and nothing else, options are plain text
(so a structured option carrying a `correct` flag cannot even be passed), and
`assert_no_answer_leak` scans the serialized request for the strings that must not be there — the
author's solution, the correct-option marker, a student's answer, a previous critique's correction,
or a rubric field with the answer key in it. The caller supplies those as *sentinels* in tests and
in the pipeline's own guard, so a regression fails loudly instead of quietly weakening the claim.

What this module deliberately does **not** do yet: it does not call a provider, store a receipt, or
wire itself into the exercise path. Those belong to the pipeline stage that owns the transaction,
and they are listed in `COURSEJESUS_LEARNING_ENGINE_STATE.md` rather than implied here.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

# The closed whitelist. A field that is not here cannot reach the blind solver, which is the whole
# point: the way a blind solve stops being blind is by growing "one more helpful field".
BLIND_SOLVE_FIELDS: Final[tuple[str, ...]] = (
    "question_text",
    "options",
    "allowed_rules",
    "task",
)

# Field names that must never appear anywhere in a blind-solve payload. They are checked by key as
# well as by value, because a payload that carries `"correct_option": "B"` is exactly as leaky as
# one whose prose mentions it.
FORBIDDEN_FIELD_NAMES: Final[tuple[str, ...]] = (
    "author_solution",
    "answer",
    "answer_key",
    "correct_option",
    "correct_options",
    "student_answer",
    "grading",
    "rubric",
    "critique",
    "reasoning",
)

DEFAULT_TASK: Final[str] = (
    "Solve the question below independently. Show the steps you used. If the question is "
    "ambiguous, under-specified or not solvable as written, say so explicitly instead of "
    "assuming the missing information."
)


class BlindSolveLeak(RuntimeError):
    """Raised when something that could reveal the answer reaches the blind-solve request."""


@dataclass(frozen=True)
class BlindSolveRequest:
    """The only thing the blind solver is allowed to see.

    `options` are **plain strings**: a caller that holds structured options with a correctness flag
    has to project them to text first, and that projection is where the flag is dropped.
    """

    question_text: str
    options: tuple[str, ...] = ()
    allowed_rules: tuple[str, ...] = ()
    task: str = DEFAULT_TASK

    def __post_init__(self) -> None:
        if not self.question_text.strip():
            raise ValueError("a blind solve needs the finished question text")
        for name, values in (("options", self.options), ("allowed_rules", self.allowed_rules)):
            for value in values:
                if not isinstance(value, str):
                    raise TypeError(
                        f"{name} must contain plain strings; a structured option carrying a "
                        f"correctness flag would defeat the isolation this module exists for"
                    )

    def payload(self) -> dict[str, object]:
        """The exact mapping that may be sent, in the whitelist's order."""
        return {
            "question_text": self.question_text,
            "options": list(self.options),
            "allowed_rules": list(self.allowed_rules),
            "task": self.task,
        }

    def input_hash(self) -> str:
        """Stable identity of the request, so a receipt can be tied to what was actually solved."""
        canonical = json.dumps(self.payload(), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()


def assert_no_answer_leak(
    request: BlindSolveRequest | Mapping[str, object],
    forbidden_values: Sequence[str] = (),
) -> None:
    """Refuse a blind-solve request that carries a known answer or a forbidden field.

    `forbidden_values` are the concrete strings the caller must not leak — the author's solution
    text, the correct option, a student's answer, a critique's correction, a rubric's answer key.
    Empty strings are ignored: a caller that passes its whole answer set should not have to filter
    the blanks, and an empty sentinel would match everything.

    Raises:
        BlindSolveLeak: naming what was found, by field or by sentinel, never echoing the secret
            itself into the message.
    """
    payload = request.payload() if isinstance(request, BlindSolveRequest) else dict(request)
    # Forbidden names are checked first so that a payload carrying `correct_option` is reported as
    # what it is — an answer leak — rather than as a mere unknown field.
    lowered = {str(key).casefold() for key in payload}
    forbidden_keys = sorted(name for name in FORBIDDEN_FIELD_NAMES if name in lowered)
    if forbidden_keys:
        raise BlindSolveLeak(f"blind-solve payload carries forbidden fields: {forbidden_keys}")
    unknown = sorted(set(payload) - set(BLIND_SOLVE_FIELDS))
    if unknown:
        raise BlindSolveLeak(
            f"blind-solve payload has fields outside the whitelist: {unknown}. "
            f"Allowed: {list(BLIND_SOLVE_FIELDS)}"
        )

    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True).casefold()
    hits: list[str] = []
    for index, value in enumerate(forbidden_values):
        text = (value or "").strip()
        if not text:
            continue
        if text.casefold() in serialized:
            # The sentinel's *index* is reported, not its content: this message can end up in a
            # log, and the sentinel is normally a piece of the answer.
            hits.append(f"sentinel #{index}")
    if hits:
        raise BlindSolveLeak(
            "blind-solve payload contains text from the answer side: "
            + ", ".join(hits)
            + ". The author's solution, the correct option, a student answer, a critique's "
            "correction and any rubric key must not reach the independent solve."
        )


@dataclass(frozen=True)
class BlindSolveReceipt:
    """What a completed blind solve must record to be usable as evidence.

    The two revisions are separate on purpose: editing the question invalidates the solve
    (`is_current_for`), and a receipt whose question revision is not the one being published is
    not evidence about that question.
    """

    input_hash: str
    question_revision: str
    model_version: str
    output: str
    status: str

    def is_current_for(self, question_revision: str) -> bool:
        """True only when this solve was run against the revision now under validation."""
        return (
            self.status == "completed"
            and bool(self.output.strip())
            and self.question_revision == question_revision
        )
