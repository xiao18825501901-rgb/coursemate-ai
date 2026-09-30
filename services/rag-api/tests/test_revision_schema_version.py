"""A stored revision must be reproduced under the schema that wrote it.

The author-output schema version is an author-output field, so it is inside the
hashed revision payload.  Recomputing a stored row with the *current* constant
therefore compares two different payloads, and it does so silently: the row is
refused as "does not reproduce its stored revision hash" with no hint that the
cause is a version bump rather than a changed question.

That is not hypothetical.  Every stored revision in production was written under
`question-author-output.v3` while the code defines `.v4`, so all nine
review-only recoverable candidates were refused, and the recovery path the owner
authorised -- reuse the existing authoring, add only a review -- could not rebuild
a single one.  Measured on the live database: 12 of 12 stored revisions reproduce
exactly once the recorded version is supplied.
"""
from __future__ import annotations

from app.learning.question_author import (
    QUESTION_AUTHOR_SCHEMA_VERSION,
    QuestionAuthorOutput,
    _question_revision_identity,
)

_OLDER_SCHEMA = "question-author-output.v3"


def _output() -> QuestionAuthorOutput:
    return QuestionAuthorOutput(
        question_text="Explain why the repeat step assigns before it recomputes.",
        options=[],
        candidate_answer="Because the centroids must be derived from the assignment.",
        correct_option_index=None,
        distractor_rationales=[],
        rule_violation_analysis=None,
        solution_steps=[
            {
                "ordinal": 1,
                "operation": "state",
                "result": "assignment precedes recomputation",
                "explanation": "The course text orders assignment before recomputation.",
                "source_refs": ["chk_00000000000000000000000000000001"],
            }
        ],
        source_refs=["chk_00000000000000000000000000000001"],
    )


def test_the_current_schema_is_what_this_code_authors_under() -> None:
    assert QUESTION_AUTHOR_SCHEMA_VERSION == "question-author-output.v4"


def test_a_revision_reproduces_under_the_schema_that_wrote_it() -> None:
    output = _output()
    hashed_under_older = _question_revision_identity(
        blueprint_hash="a" * 64,
        evidence_pack_hash="b" * 64,
        output=output,
        schema_version=_OLDER_SCHEMA,
    )
    # Reproducing it needs the version that produced it...
    assert (
        _question_revision_identity(
            blueprint_hash="a" * 64,
            evidence_pack_hash="b" * 64,
            output=output,
            schema_version=_OLDER_SCHEMA,
        )
        == hashed_under_older
    )
    # ...and today's constant gives a different hash for identical content, which
    # is exactly the trap that refused every historical row.
    assert (
        _question_revision_identity(
            blueprint_hash="a" * 64, evidence_pack_hash="b" * 64, output=output
        )
        != hashed_under_older
    )


def test_the_default_still_hashes_under_the_current_schema() -> None:
    output = _output()
    assert _question_revision_identity(
        blueprint_hash="a" * 64, evidence_pack_hash="b" * 64, output=output
    ) == _question_revision_identity(
        blueprint_hash="a" * 64,
        evidence_pack_hash="b" * 64,
        output=output,
        schema_version=QUESTION_AUTHOR_SCHEMA_VERSION,
    )
