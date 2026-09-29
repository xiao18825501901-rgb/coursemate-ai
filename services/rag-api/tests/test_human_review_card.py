"""The human review card's contract.

The card is the one place a person replaces a model, so its constraints are
tested in both directions: it must be *authoritative* for the single case it
covers, and it must be *incapable* of touching anything else or of surviving a
change to the item it reviewed.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.config import Settings
from app.db import Database
from app.learning.human_review_card import (
    CARD_QUESTIONS,
    MAX_CARD_AGE_DAYS,
    HumanReviewCard,
    HumanReviewStore,
    build_card_prompt,
)
from app.learning.hybrid_review import (
    ADVERSARIAL_AUDIT_ROLE,
    CASE_AGREEMENT,
    CASE_AMBIGUITY,
    CASE_DISTRACTORS,
    EVIDENCE_AUDIT_ROLE,
    JudgeDependency,
    SpecificationEnumeration,
    combine_case_verdicts,
)

REVISION = "a" * 64


def _card(**overrides) -> HumanReviewCard:
    payload = {
        "question_revision_hash": REVISION,
        "decision": "PASS",
        "dependencies": [
            {
                "datum": "the two integers stated in the stem",
                "stated_in_stem": True,
            }
        ],
        "reviewer_user_id": "user-owner",
        "reviewed_at": datetime.now(UTC).isoformat(),
        "note": "checked against the stem",
    }
    payload.update(overrides)
    return HumanReviewCard(**payload)


def _both_roles(verdict: str) -> dict[str, dict[str, str]]:
    return {
        EVIDENCE_AUDIT_ROLE: {CASE_AMBIGUITY: verdict, CASE_AGREEMENT: "PASS"},
        ADVERSARIAL_AUDIT_ROLE: {CASE_AMBIGUITY: verdict, CASE_AGREEMENT: "PASS"},
    }


# --------------------------------------------------------------- authority


def test_a_card_is_authoritative_for_the_case_it_covers() -> None:
    """The reviewers cannot judge this case, so a person replaces them on it.

    Both roles refuse the ambiguity case and the card passes it; the card wins,
    because that is the whole purpose of having a card.
    """
    combined, reasons = combine_case_verdicts(
        required_cases=(CASE_AMBIGUITY, CASE_AGREEMENT),
        by_role=_both_roles("FAIL"),
        human_card=_card(),
    )
    assert combined[CASE_AMBIGUITY] == "PASS"
    assert combined[CASE_AGREEMENT] == "PASS"
    assert "HYBRID_CASE_FAIL:" + CASE_AMBIGUITY not in reasons


def test_a_card_can_also_refuse_where_the_reviewers_passed() -> None:
    blocking = JudgeDependency(
        datum="the value the answer is computed from",
        stated_in_stem=False,
        answer_changes_if_absent=True,
        consequence="a different value gives a different answer",
    )
    combined, reasons = combine_case_verdicts(
        required_cases=(CASE_AMBIGUITY, CASE_AGREEMENT),
        by_role=_both_roles("PASS"),
        human_card=_card(decision="FAIL", dependencies=[blocking]),
    )
    assert combined[CASE_AMBIGUITY] == "FAIL"
    assert combined[CASE_AGREEMENT] == "PASS"
    assert any(r.startswith("HYBRID_UNSTATED_DEPENDENCY") for r in reasons)


def test_a_card_cannot_touch_any_other_case() -> None:
    """The card exists for one case; the other three stay with the reviewers."""
    blocked = _both_roles("PASS")
    blocked[EVIDENCE_AUDIT_ROLE][CASE_DISTRACTORS] = "PASS"
    blocked[ADVERSARIAL_AUDIT_ROLE][CASE_DISTRACTORS] = "FAIL"
    combined, _ = combine_case_verdicts(
        required_cases=(CASE_AMBIGUITY, CASE_DISTRACTORS),
        by_role=blocked,
        human_card=_card(),
    )
    assert combined[CASE_DISTRACTORS] == "FAIL"


def test_without_a_card_the_case_needs_evidence_rather_than_two_votes() -> None:
    """The card is no longer the only alternative to the reviewer verdicts.

    With no card, the case is decided by evidence: a verified witness fails it, an
    unverified objection holds it, and approval needs the server's completeness
    certificate plus an active qualification.  Two favourable verdicts and a clean
    specification pass are not enough on their own, and a bare refusal without a
    witness no longer decides it either.
    """
    from app.learning.task_spec import CompletenessEvidence

    clean = SpecificationEnumeration(
        dependencies=[JudgeDependency(datum="the stated values", stated_in_stem=True)]
    )
    certificate = CompletenessEvidence(
        status="COMPLETE_FOR_REGISTERED_PROFILE",
        profile_id="P-SQL",
        profile_version=1,
        renderer_version="public-projection.v1",
        checker="sql_oracle.v1",
        projection_digest="a" * 64,
        question_revision_hash="b" * 64,
    )
    passed, reasons = combine_case_verdicts(
        required_cases=(CASE_AMBIGUITY,),
        by_role=_both_roles("PASS"),
        specification=clean,
    )
    assert passed[CASE_AMBIGUITY] == "UNCERTAIN"
    assert "HYBRID_COMPLETENESS_CERTIFICATE_MISSING" in reasons
    assert "HYBRID_QUALIFICATION_MISSING" in reasons

    certified, certified_reasons = combine_case_verdicts(
        required_cases=(CASE_AMBIGUITY,),
        by_role=_both_roles("PASS"),
        specification=clean,
        completeness=certificate,
        qualification_active=True,
    )
    assert certified[CASE_AMBIGUITY] == "PASS"
    assert not any(
        reason.startswith("HYBRID_COMPLETENESS_CERTIFICATE_MISSING")
        or reason == "HYBRID_QUALIFICATION_MISSING"
        for reason in certified_reasons
    )

    # The automatic pass still cannot upgrade a case it refuses.
    blocking = SpecificationEnumeration(
        dependencies=[
            JudgeDependency(
                datum="the value the answer is computed from",
                stated_in_stem=False,
                answer_changes_if_absent=True,
                consequence="a different value gives a different answer",
            )
        ]
    )
    # The pass no longer decides it: with a certificate the entry is answered and
    # the case passes; without one the same entry holds the item.
    refused_by_pass, _ = combine_case_verdicts(
        required_cases=(CASE_AMBIGUITY,),
        by_role=_both_roles("PASS"),
        specification=blocking,
        completeness=certificate,
        qualification_active=True,
    )
    assert refused_by_pass[CASE_AMBIGUITY] == "PASS"
    held_without_certificate, _ = combine_case_verdicts(
        required_cases=(CASE_AMBIGUITY,),
        by_role=_both_roles("PASS"),
        specification=blocking,
        qualification_active=True,
    )
    assert held_without_certificate[CASE_AMBIGUITY] == "UNCERTAIN"

    # And a bare refusal without a witness no longer decides it.
    refused_by_roles, _ = combine_case_verdicts(
        required_cases=(CASE_AMBIGUITY,),
        by_role=_both_roles("FAIL"),
        specification=clean,
        completeness=certificate,
        qualification_active=True,
    )
    assert refused_by_roles[CASE_AMBIGUITY] == "PASS"


# ------------------------------------------------------------ substantiation


def test_a_card_cannot_pass_while_its_own_list_records_a_missing_datum() -> None:
    blocking = {
        "datum": "the value of epsilon",
        "stated_in_stem": False,
        "answer_changes_if_absent": True,
        "consequence": "a different count results",
    }
    with pytest.raises(ValueError):
        _card(dependencies=[blocking])


def test_a_card_that_fails_must_say_which_datum_is_absent() -> None:
    with pytest.raises(ValueError):
        _card(
            decision="FAIL",
            dependencies=[{"datum": "the stated values", "stated_in_stem": True}],
        )


def test_a_card_needs_at_least_one_entry() -> None:
    with pytest.raises(ValueError):
        _card(dependencies=[])


def test_a_card_timestamp_must_carry_a_timezone() -> None:
    with pytest.raises(ValueError):
        _card(reviewed_at="2026-09-30T02:00:00")
    with pytest.raises(ValueError):
        _card(reviewed_at="not a timestamp at all")


# ----------------------------------------------------------------- storage


def _database(tmp_path: Path) -> Database:
    database = Database(
        Settings(
            app_name="coursemate",
            app_env="test",
            database_path=tmp_path / "rag.sqlite3",
            upload_dir=tmp_path / "uploads",
            v3_enabled=True,
            rag_provider_mode="deterministic",
        )
    )
    database.initialize()
    return database


def test_a_stored_card_is_returned_for_its_own_revision_only(tmp_path: Path) -> None:
    database = _database(tmp_path)
    store = HumanReviewStore(database)
    card_id = store.record(_card(), owner_user_id="user-owner")
    found = store.current_for(question_revision_hash=REVISION)
    assert found is not None
    assert found[0] == card_id
    assert found[1].decision == "PASS"
    assert store.current_for(question_revision_hash="b" * 64) is None
    assert store.current_for(
        question_revision_hash=REVISION, policy_revision="hybrid-strict-v2"
    ) is None


def test_an_expired_card_is_not_returned(tmp_path: Path) -> None:
    database = _database(tmp_path)
    store = HumanReviewStore(database)
    old = datetime.now(UTC) - timedelta(days=MAX_CARD_AGE_DAYS + 1)
    store.record(_card(reviewed_at=old.isoformat()), owner_user_id="user-owner")
    assert store.current_for(question_revision_hash=REVISION) is None
    # It is still there for audit; it simply no longer authorises anything.
    with database.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM hybrid_human_reviews"
        ).fetchone()[0] == 1


def test_a_superseding_card_is_used_and_the_old_one_is_kept(tmp_path: Path) -> None:
    database = _database(tmp_path)
    store = HumanReviewStore(database)
    store.record(
        _card(reviewed_at=(datetime.now(UTC) - timedelta(days=2)).isoformat()),
        owner_user_id="user-owner",
    )
    blocking = JudgeDependency(
        datum="the value of epsilon",
        stated_in_stem=False,
        answer_changes_if_absent=True,
        consequence="a different count results",
    )
    newest = store.record(
        _card(decision="FAIL", dependencies=[blocking]), owner_user_id="user-owner"
    )
    found = store.current_for(question_revision_hash=REVISION)
    assert found is not None and found[0] == newest
    assert found[1].decision == "FAIL"
    with database.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM hybrid_human_reviews"
        ).fetchone()[0] == 2


def test_cards_are_immutable(tmp_path: Path) -> None:
    import sqlite3

    database = _database(tmp_path)
    store = HumanReviewStore(database)
    card_id = store.record(_card(), owner_user_id="user-owner")
    with database.connect() as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE hybrid_human_reviews SET decision='FAIL' WHERE id=?", (card_id,)
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM hybrid_human_reviews WHERE id=?", (card_id,))


def test_a_malformed_stored_card_is_skipped_not_repaired_into_a_pass(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    store = HumanReviewStore(database)
    store.record(_card(), owner_user_id="user-owner")
    with database.connect() as connection:
        # Bypass the model by writing a row the schema would have refused.
        connection.execute("DROP TRIGGER hybrid_human_reviews_no_update")
        connection.execute(
            "UPDATE hybrid_human_reviews SET dependencies_json=? WHERE reviewer_user_id=?",
            ('[{"datum": "x"}]', "user-owner"),
        )
    assert store.current_for(question_revision_hash=REVISION) is None


# -------------------------------------------------------------------- card


def test_the_card_carries_content_rather_than_a_blank_signature() -> None:
    prompt = build_card_prompt(
        question_revision_hash=REVISION,
        question_type="NUMERIC",
        stem="Compute the value.",
        options=("a", "b"),
        source_spans=({"evidence_id": "ev-1", "content": "rule text"},),
    )
    assert prompt.stem == "Compute the value."
    assert len(prompt.open_questions) == len(CARD_QUESTIONS) >= 5
    record = prompt.as_record()
    # The durable record describes the card without reproducing the item.
    assert "Compute the value." not in str(record)
    assert record["stem_chars"] == len("Compute the value.")
