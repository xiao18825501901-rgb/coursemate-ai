"""The human review card for the one case the reviewers cannot decide.

Nine measured runs established that the under-specification judgement cannot be
made both safe and usable by instructing the reviewer configuration: detection and
coverage move together, and no point on the frontier qualifies
(`HYBRID_QUALIFICATION_AND_REGRESSION.md` §3.05).  The brief anticipates exactly
this situation and asks for what genuinely needs a person to be concentrated into
a small, content-bearing card rather than spread over the whole pipeline.  This
module is that card, and it is confined to **one** of the four quality cases.

What the card is:

* a structured decision on `question.ambiguity.v1` only, carrying the same
  dependency enumeration the automatic specification pass produces, so the person
  is confirming or correcting facts rather than signing a blank;
* bound to one exact question revision, one policy revision and one reviewer
  identity, and stored append-only;
* **never** an approval of the other three cases.  `answer_agreement`,
  `mcq_distractor_quality` and `rule_violation_quality` remain decided by the two
  isolated reviewers and by the executable oracle, and a card cannot touch them.

What the card is not: a bypass.  A missing, stale, malformed or out-of-scope card
leaves the ambiguity case abstained, which is the same closed state the pipeline
is in today; a card whose enumeration contains a blocking entry fails the case
even if it says `PASS`; and a card can never turn a deterministic failure or a
reviewer `FAIL` into a pass, because the merge rule is applied after them and can
only remove approvals.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Final, Literal
from uuid import uuid4

from pydantic import Field, StringConstraints, model_validator

from app.db import Database
from app.learning.hybrid_review import (
    CASE_AMBIGUITY,
    POLICY_REVISION,
    JudgeDependency,
    SpecificationEnumeration,
    ambiguity_verdict_from_enumeration,
)
from app.learning.models import Contract, Identifier

HUMAN_CARD_VERSION: Final = "human-specification-card.v1"
# The card is only valid while the item it reviewed has not changed.  A card is
# bound to the revision hash, so "changed" is exact rather than approximate.
MAX_CARD_AGE_DAYS: Final = 30


class HumanReviewCardError(RuntimeError):
    """A card could not be accepted; never carries private question text."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class HumanReviewCard(Contract):
    """One person's decision on one question's under-specification case."""

    schema_version: Literal["human-specification-card.v1"] = HUMAN_CARD_VERSION
    policy_revision: str = POLICY_REVISION
    question_revision_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    # The card decides the ambiguity case and nothing else, so the field exists
    # only to make that explicit in the record rather than implicit in the code.
    case: Literal["question.ambiguity.v1"] = CASE_AMBIGUITY
    decision: Literal["PASS", "FAIL"]
    dependencies: list[JudgeDependency] = Field(min_length=1, max_length=24)
    reviewer_user_id: Identifier
    reviewed_at: str = Field(min_length=20, max_length=40)
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] = ""

    @model_validator(mode="after")
    def a_decision_is_substantiated_by_its_enumeration(self) -> HumanReviewCard:
        blocking = [item for item in self.dependencies if item.blocks_the_item]
        if self.decision == "PASS" and blocking:
            raise ValueError(
                "a card cannot pass an item while its own enumeration records a "
                "dependency that is unstated and changes the answer"
            )
        if self.decision == "FAIL" and not blocking:
            raise ValueError(
                "a card that fails the item must record which dependency is "
                "absent and what different answer results"
            )
        try:
            reviewed = datetime.fromisoformat(self.reviewed_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("reviewed_at must be an ISO-8601 timestamp") from error
        if reviewed.tzinfo is None:
            raise ValueError("reviewed_at must carry a timezone")
        return self

    @property
    def enumeration(self) -> SpecificationEnumeration:
        return SpecificationEnumeration(dependencies=self.dependencies)

    def age_days(self, *, now: datetime | None = None) -> float:
        reviewed = datetime.fromisoformat(self.reviewed_at.replace("Z", "+00:00"))
        return ((now or datetime.now(UTC)) - reviewed).total_seconds() / 86_400

    @property
    def blocking_entries(self) -> list[JudgeDependency]:
        return [item for item in self.dependencies if item.blocks_the_item]


class HumanReviewStore:
    """Append-only storage for human cards."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def record(self, card: HumanReviewCard, *, owner_user_id: str) -> str:
        card_id = f"humancard-{uuid4().hex}"
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO hybrid_human_reviews("
                "id,question_revision_hash,policy_revision,case_key,decision,"
                "dependencies_json,reviewer_user_id,owner_user_id,reviewed_at,note,"
                "card_version) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    card_id,
                    card.question_revision_hash,
                    card.policy_revision,
                    card.case,
                    card.decision,
                    json.dumps(
                        [item.model_dump(mode="json") for item in card.dependencies],
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    card.reviewer_user_id,
                    owner_user_id,
                    card.reviewed_at,
                    card.note,
                    card.schema_version,
                ),
            )
        return card_id

    def current_for(
        self,
        *,
        question_revision_hash: str,
        policy_revision: str = POLICY_REVISION,
        now: datetime | None = None,
    ) -> tuple[str, HumanReviewCard] | None:
        """The newest valid card for this exact revision, or ``None``.

        Validity is re-checked on every read: an expired card, a card for a
        different policy revision, or a card for a different question revision is
        not returned, and the caller therefore treats the case as abstained.
        """
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM hybrid_human_reviews "
                "WHERE question_revision_hash=? AND policy_revision=? AND case_key=? "
                "ORDER BY reviewed_at DESC, created_at DESC",
                (question_revision_hash, policy_revision, CASE_AMBIGUITY),
            ).fetchall()
        for row in rows:
            try:
                card = HumanReviewCard(
                    policy_revision=str(row["policy_revision"]),
                    question_revision_hash=str(row["question_revision_hash"]),
                    case=str(row["case_key"]),
                    decision=str(row["decision"]),
                    dependencies=json.loads(str(row["dependencies_json"])),
                    reviewer_user_id=str(row["reviewer_user_id"]),
                    reviewed_at=str(row["reviewed_at"]),
                    note=str(row["note"] or ""),
                )
            except (ValueError, TypeError):
                # A malformed stored card is skipped, never repaired into a pass.
                continue
            if card.age_days(now=now) > MAX_CARD_AGE_DAYS:
                continue
            return str(row["id"]), card
        return None


def card_ambiguity_verdict(
    card: HumanReviewCard | None,
) -> tuple[str, str]:
    """The ambiguity verdict a card produces, or an abstention without one.

    The card's stated decision and its own enumeration must agree -- the schema
    already refuses a disagreement -- so this reads the enumeration through the
    same function the automatic pass uses, which keeps one rule for both.
    """
    if card is None:
        return "UNCERTAIN", "HYBRID_HUMAN_CARD_MISSING"
    derived, reason = ambiguity_verdict_from_enumeration(card.enumeration)
    if derived != card.decision:
        # Cannot happen through the schema, but the gate does not rely on that.
        return "UNCERTAIN", "HYBRID_HUMAN_CARD_INCONSISTENT"
    return derived, reason


@dataclass(frozen=True)
class ReviewCardPrompt:
    """The content an owner is asked to review, with no private text in the log."""

    question_revision_hash: str
    question_type: str
    stem: str
    options: tuple[str, ...]
    source_spans: tuple[dict[str, str], ...]
    open_questions: tuple[str, ...]

    def as_record(self) -> dict[str, Any]:
        return {
            "question_revision_hash": self.question_revision_hash,
            "question_type": self.question_type,
            "stem_chars": len(self.stem),
            "options": len(self.options),
            "source_spans": len(self.source_spans),
            "open_questions": list(self.open_questions),
        }


# The questions a person must answer, phrased so a "yes" is checkable against the
# stem rather than a feeling about it.  They mirror the enumeration fields, which
# is what makes the card's output machine-usable.
CARD_QUESTIONS: Final[tuple[str, ...]] = (
    "Does the stem state every value the answer is computed from?",
    "Does the stem state the units, scale and rounding convention?",
    "Does the stem state any boundary convention the answer turns on "
    "(endpoints, self-inclusion, directed versus undirected)?",
    "For data tasks: does the stem state the schema, dialect, ordering, and the "
    "treatment of NULL and duplicate rows?",
    "Does answering require anything the supplied sources do not contain?",
    "Is any requirement the answer turns on missing from the stem -- for example "
    "a dropped 'only if', 'at least' or 'provided that' clause?",
)


def build_card_prompt(
    *,
    question_revision_hash: str,
    question_type: str,
    stem: str,
    options: tuple[str, ...] = (),
    source_spans: tuple[dict[str, str], ...] = (),
) -> ReviewCardPrompt:
    """Assemble the card's content.  Callers must not log the returned stem."""
    return ReviewCardPrompt(
        question_revision_hash=question_revision_hash,
        question_type=question_type,
        stem=stem,
        options=options,
        source_spans=source_spans,
        open_questions=CARD_QUESTIONS,
    )
