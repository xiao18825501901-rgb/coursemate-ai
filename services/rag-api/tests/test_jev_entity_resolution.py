"""CourseEntityResolution: deterministic-first, Jev-on-residue, relations-only.

Every test uses the offline :class:`FakeTransport` — no live Jev call is made, and
none is claimed. The suite pins the module's hard guarantees: byte-identical
duplicates cost zero Jev; an accepted alias is authoritative; similarity is not
proof (a same-word pair stays DIFFERENT); relations are never transitive and never
merge; the pair budget is honoured with unchecked pairs recorded; scope isolation
drops out-of-scope objects before pairing; alias query expansion preserves the
original query and never overrides an explicit target; a transport failure degrades
to no relation; and no learning/grade/coverage row is written.
"""

from __future__ import annotations

from jev_fixtures import make_jev_database

from app.jev.entity_resolution import (
    ALIAS,
    DIFFERENT,
    DOCUMENT_VERSION_RELATION,
    ENTITY_RELATION_KEY,
    QUESTION_VARIANT,
    SAME_CONCEPT,
    UNCERTAIN,
    EntityObject,
    expand_query,
    generate_candidate_pairs,
    resolve_relations,
)
from app.jev.errors import JevUnavailableError
from app.jev.gateway import FakeTransport, JevGateway
from app.jev.models import JevAnswer, JevResult
from app.jev.receipt_store import SqlReceiptStore

KEY = ENTITY_RELATION_KEY
CS = "cs101"


def make_object(
    object_id: str,
    *,
    kind: str = "concept",
    course_id: str = CS,
    material_revision: str = "r1",
    label: str | None = None,
    content: str = "",
    aliases: tuple[str, ...] = (),
    source_version: str | None = None,
) -> EntityObject:
    return EntityObject(
        object_id=object_id,
        kind=kind,
        course_id=course_id,
        material_revision=material_revision,
        label=label if label is not None else object_id,
        content=content,
        aliases=aliases,
        source_version=source_version,
    )


def make_gateway(responder=None, *, store=None, modes=None) -> JevGateway:
    return JevGateway(
        transport=FakeTransport(responder),
        modes=modes or {KEY: "on"},
        receipt_store=store,
    )


def _choice_responder(choice: str):
    def responder(call):
        return JevResult(answers={KEY: JevAnswer(choice=choice)})

    return responder


# --------------------------------------------------------------------------- #
# Exact duplicates cost zero Jev (byte-identical content, decided by hash)
# --------------------------------------------------------------------------- #


def test_byte_identical_duplicate_resolved_by_hash_with_zero_jev() -> None:
    gateway = make_gateway(_choice_responder(SAME_CONCEPT))
    objects = [
        make_object("ev-1", kind="evidence", label="derivative notes", content="d/dx x^2 = 2x"),
        make_object("ev-2", kind="evidence", label="derivative notes", content="d/dx x^2 = 2x"),
    ]
    report = resolve_relations(gateway, objects, course_id=CS)

    assert len(report.relations) == 1
    relation = report.relations[0]
    assert relation.relation == SAME_CONCEPT
    assert relation.reason == "content_hash"
    assert relation.used_jev is False
    assert gateway.transport.calls == []  # byte-identical content never reaches Jev
    assert report.duplicates == [relation]
    assert report.merged_any is False


def test_exact_id_match_resolves_deterministically_without_jev() -> None:
    gateway = make_gateway(_choice_responder(SAME_CONCEPT))
    objects = [
        make_object("node-1", label="导数"),
        make_object("node-1", label="derivative"),
    ]
    report = resolve_relations(gateway, objects, course_id=CS)

    assert len(report.relations) == 1
    assert report.relations[0].relation == SAME_CONCEPT
    assert report.relations[0].reason == "exact_id"
    assert report.relations[0].used_jev is False
    assert gateway.transport.calls == []


# --------------------------------------------------------------------------- #
# Alias handling (accepted alias is authoritative; Jev may accept a new one)
# --------------------------------------------------------------------------- #


def test_accepted_alias_resolves_deterministically_zero_jev() -> None:
    gateway = make_gateway(_choice_responder(ALIAS))
    objects = [
        make_object("term-cn", kind="term", label="导数", aliases=("derivative",)),
        make_object("term-en", kind="term", label="derivative"),
    ]
    report = resolve_relations(gateway, objects, course_id=CS)

    assert report.aliases == report.relations
    relation = report.relations[0]
    assert relation.relation == ALIAS
    assert relation.reason == "alias"
    assert relation.used_jev is False
    assert gateway.transport.calls == []  # an already-accepted alias costs zero Jev


def test_jev_accepts_a_new_alias_with_shared_tokens() -> None:
    gateway = make_gateway(_choice_responder(ALIAS))
    objects = [
        make_object(
            "term-a", kind="term", label="derivative", content="the derivative of a function"
        ),
        make_object(
            "term-b",
            kind="term",
            label="differentiation",
            content="differentiation is the derivative of a function",
        ),
    ]
    report = resolve_relations(gateway, objects, course_id=CS)

    assert len(report.relations) == 1
    relation = report.relations[0]
    assert relation.relation == ALIAS
    assert relation.used_jev is True
    assert len(gateway.transport.calls) == 1


# --------------------------------------------------------------------------- #
# Similarity is not proof: same word, different meaning stays DIFFERENT
# --------------------------------------------------------------------------- #


def test_same_word_different_meaning_is_different_not_merged() -> None:
    gateway = make_gateway(_choice_responder(DIFFERENT))
    objects = [
        make_object("bank-river", kind="term", label="bank", content="the side of a river"),
        make_object("bank-money", kind="term", label="bank", content="a financial institution"),
    ]
    report = resolve_relations(gateway, objects, course_id=CS)

    assert len(report.relations) == 1
    relation = report.relations[0]
    assert relation.reason == "title"  # normalized titles match -> offered to Jev
    assert relation.relation == DIFFERENT
    assert relation.used_jev is True
    assert report.merged_any is False  # never merged despite the identical label


# --------------------------------------------------------------------------- #
# Question variants and material versions
# --------------------------------------------------------------------------- #


def test_question_variant_pair() -> None:
    gateway = make_gateway(_choice_responder(QUESTION_VARIANT))
    objects = [
        make_object(
            "q-1",
            kind="question",
            label="Solve the quadratic",
            content="solve the quadratic equation x squared plus three x plus two equals zero",
        ),
        make_object(
            "q-2",
            kind="question",
            label="Find the roots",
            content="find the roots of the quadratic equation x squared plus three x plus two",
        ),
    ]
    report = resolve_relations(gateway, objects, course_id=CS)

    assert len(report.relations) == 1
    relation = report.relations[0]
    assert relation.relation == QUESTION_VARIANT
    assert relation.used_jev is True
    assert report.merged_any is False


def test_version_relation_resolved_deterministically_zero_jev() -> None:
    gateway = make_gateway(_choice_responder(DOCUMENT_VERSION_RELATION))
    objects = [
        make_object("mat-1", kind="material", label="syllabus", material_revision="r1"),
        make_object("mat-1", kind="material", label="syllabus", material_revision="r2"),
    ]
    report = resolve_relations(gateway, objects, course_id=CS)

    assert len(report.relations) == 1
    relation = report.relations[0]
    assert relation.relation == DOCUMENT_VERSION_RELATION
    assert relation.reason == "version"
    assert relation.used_jev is False
    assert gateway.transport.calls == []
    assert report.version_relations == [relation]


# --------------------------------------------------------------------------- #
# Non-transitivity: A≈B and B≈C must not relate A and C
# --------------------------------------------------------------------------- #


def test_non_transitive_pairs_do_not_merge_across_the_chain() -> None:
    gateway = make_gateway(_choice_responder(SAME_CONCEPT))
    objects = [
        make_object("A", label="A", content="alpha beta common"),
        make_object("B", label="B", content="beta common gamma"),
        make_object("C", label="C", content="common gamma delta"),
    ]
    pairs = generate_candidate_pairs(objects).pairs
    # A≈B and B≈C are comparable; A≉C is below the threshold and is never offered.
    pair_ids = {frozenset((p.left_id, p.right_id)) for p in pairs}
    assert frozenset(("A", "B")) in pair_ids
    assert frozenset(("B", "C")) in pair_ids
    assert frozenset(("A", "C")) not in pair_ids

    report = resolve_relations(gateway, objects, course_id=CS)
    assert len(report.relations) == 2
    resolved_ids = {frozenset((r.left_id, r.right_id)) for r in report.relations}
    assert frozenset(("A", "B")) in resolved_ids
    assert frozenset(("B", "C")) in resolved_ids
    assert frozenset(("A", "C")) not in resolved_ids
    assert report.merged_any is False  # no cluster id, no A–C relation, nothing merged


# --------------------------------------------------------------------------- #
# Symmetry + candidate cap (order-independent, dropped pairs recorded)
# --------------------------------------------------------------------------- #


def test_candidate_generation_is_symmetric_regardless_of_left_right() -> None:
    a = make_object("A", label="A", content="alpha beta common")
    b = make_object("B", label="B", content="beta common gamma")
    forward = generate_candidate_pairs([a, b])
    backward = generate_candidate_pairs([b, a])
    assert forward.pairs == backward.pairs  # identical, regardless of input order
    assert len(forward.pairs) == 1
    pair = forward.pairs[0]
    assert pair.left_id == "A" and pair.right_id == "B"  # canonical, not input, order
    assert pair.reason == "similarity"


def test_candidate_pair_cap_is_order_independent_and_records_drops() -> None:
    objects = [
        make_object(f"chunk-{i}", kind="evidence", label="derivative", content=f"note {i}")
        for i in range(6)
    ]
    result = generate_candidate_pairs(objects, max_candidate_pairs=4)
    assert result.scored == 15  # 6 choose 2 title candidates
    assert len(result.pairs) == 4
    assert result.dropped_by_cap == 11  # 15 - 4

    # The cap is applied after scoring, in a canonical order, so reversing the
    # input cannot change which pairs survive.
    reversed_result = generate_candidate_pairs(list(reversed(objects)), max_candidate_pairs=4)
    assert reversed_result.pairs == result.pairs

    # The dropped-by-cap count flows into the report and is distinct from the
    # Jev-budget ``unchecked_pairs`` (here every kept pair fits the Jev budget).
    report = resolve_relations(None, objects, course_id=CS, max_candidate_pairs=4)
    assert report.dropped_by_cap == 11
    assert report.candidate_pairs == 4
    assert report.scored_pairs == 15
    assert report.unchecked_pairs == 0


# --------------------------------------------------------------------------- #
# Pair budget + unchecked pairs
# --------------------------------------------------------------------------- #


def test_pair_budget_honoured_with_unchecked_pairs_recorded() -> None:
    gateway = make_gateway(_choice_responder(SAME_CONCEPT))
    # Twelve evidence chunks about one concept: every pair shares the normalized
    # title, so all 66 pairs are comparable (and all are semantic residue).
    objects = [
        make_object(
            f"chunk-{i}",
            kind="evidence",
            label="derivative",
            content=f"the derivative rule for example number {i}",
        )
        for i in range(12)
    ]
    report = resolve_relations(gateway, objects, course_id=CS, max_pairs=8)

    assert report.pair_budget == 8
    assert report.semantic_pairs == 8  # the Jev budget was honoured exactly
    assert report.unchecked_pairs == 58  # 66 comparable pairs minus the 8 checked
    assert report.total_possible_pairs == 66  # 12 choose 2: never the whole corpus
    assert report.checked_pairs == 8
    assert len(gateway.transport.calls) == 8


# --------------------------------------------------------------------------- #
# Scope isolation: an out-of-scope pair is never offered
# --------------------------------------------------------------------------- #


def test_scope_isolation_out_of_scope_pair_never_offered() -> None:
    gateway = make_gateway(_choice_responder(SAME_CONCEPT))
    # A private object belonging to another course/workspace must never be paired.
    objects = [
        make_object("in-1", kind="term", label="derivative", content="rate of change"),
        make_object("in-2", kind="term", label="derivative", content="rate of change"),
        make_object(
            "other-1", kind="term", course_id="cs202", label="derivative", content="rate of change"
        ),
    ]
    report = resolve_relations(gateway, objects, course_id=CS)

    assert report.excluded_out_of_scope == ("other-1",)
    assert all(r.left_id != "other-1" and r.right_id != "other-1" for r in report.relations)
    # The out-of-scope object's identity never appears in any Jev state.
    for call in gateway.transport.calls:
        payload = str(call.state)
        assert "other-1" not in payload


# --------------------------------------------------------------------------- #
# Conservative query expansion
# --------------------------------------------------------------------------- #


def test_alias_query_expansion_preserves_original_query_and_is_bounded() -> None:
    expanded = expand_query(
        "导数", name_groups=[("导数", "derivative", "differentiation")], max_aliases=1
    )
    assert expanded.original_query == "导数"
    assert expanded.expanded_query == "导数 derivative"
    assert expanded.expanded_query.startswith("导数")  # the original is always the prefix
    assert expanded.added_aliases == ("derivative",)  # bounded to max_aliases
    assert expanded.matched_groups == ("导数",)  # …and it says why
    assert expanded.skipped_because_explicit_target is False


def test_expansion_works_in_both_directions_within_one_concept() -> None:
    """An English term gains the Chinese name and vice versa."""
    to_english = expand_query("密度聚类", name_groups=[("密度聚类", "DBSCAN")])
    assert to_english.expanded_query == "密度聚类 DBSCAN"
    to_chinese = expand_query("explain DBSCAN", name_groups=[("密度聚类", "DBSCAN")])
    assert to_chinese.expanded_query == "explain DBSCAN 密度聚类"
    assert to_chinese.original_query == "explain DBSCAN"


def test_unrelated_query_is_never_expanded_with_a_course_wide_alias_list() -> None:
    """The precision rule: an alias is only added for the concept the query names."""
    groups = [("密度聚类", "DBSCAN"), ("梯度下降", "gradient descent")]
    expanded = expand_query("谱聚类是什么", name_groups=groups)
    assert expanded.expanded_query == "谱聚类是什么"  # unchanged
    assert expanded.added_aliases == ()
    assert expanded.matched_groups == ()


def test_explicit_target_outranks_alias_expansion() -> None:
    expanded = expand_query(
        "导数 chapter5.pdf",
        name_groups=[("导数", "derivative")],
        explicit_targets=("chapter5.pdf",),
    )
    assert expanded.expanded_query == "导数 chapter5.pdf"  # unchanged, target preserved
    assert expanded.added_aliases == ()
    assert expanded.skipped_because_explicit_target is True


def test_query_expansion_never_duplicates_an_already_present_term() -> None:
    expanded = expand_query(
        "derivative rule", name_groups=[("导数", "derivative", "differentiation")]
    )
    # The matched concept's other names are added — including the canonical term,
    # which the query did not name — but never the term already present.
    assert expanded.added_aliases == ("导数", "differentiation")
    assert expanded.original_query == "derivative rule"
    assert expanded.expanded_query.startswith("derivative rule ")


# --------------------------------------------------------------------------- #
# Degradation on an unavailable transport
# --------------------------------------------------------------------------- #


def test_transport_failure_degrades_to_no_relation(tmp_path) -> None:
    database = make_jev_database(tmp_path)

    def responder(call):
        raise JevUnavailableError("down")

    gateway = make_gateway(responder, store=SqlReceiptStore(database))
    objects = [
        make_object("a", label="A", content="alpha beta common"),
        make_object("b", label="B", content="beta common gamma"),
    ]
    report = resolve_relations(gateway, objects, course_id=CS)

    assert report.relations
    assert all(r.relation == UNCERTAIN for r in report.relations)
    assert all(not r.used_jev for r in report.relations)
    assert report.merged_any is False
    # Query expansion is untouched by a transport failure (it never reaches Jev).
    expanded = expand_query("导数", name_groups=[("导数", "derivative")])
    assert expanded.expanded_query == "导数 derivative"


def test_no_gateway_is_a_typed_uncertain_fallback() -> None:
    objects = [
        make_object("a", label="A", content="alpha beta common"),
        make_object("b", label="B", content="beta common gamma"),
    ]
    report = resolve_relations(None, objects, course_id=CS)
    assert report.relations
    assert all(r.relation == UNCERTAIN for r in report.relations)
    assert all(not r.used_jev for r in report.relations)


# --------------------------------------------------------------------------- #
# No learning/grade/coverage row writes
# --------------------------------------------------------------------------- #


def test_relations_write_only_receipts(tmp_path) -> None:
    database = make_jev_database(tmp_path)
    with database.connect() as connection:
        connection.executescript(
            """
            CREATE TABLE learning_journeys (id TEXT PRIMARY KEY, node_id TEXT, status TEXT);
            CREATE TABLE assessment_sessions (id TEXT PRIMARY KEY, raw_score REAL, status TEXT);
            CREATE TABLE learning_coverage (id TEXT PRIMARY KEY, journey_id TEXT, item_id TEXT);
            INSERT INTO learning_journeys VALUES('j1','n1','LEARNING');
            INSERT INTO assessment_sessions VALUES('s1',78.0,'GRADED');
            INSERT INTO learning_coverage VALUES('c1','j1','item-a');
            """
        )

    gateway = make_gateway(_choice_responder(ALIAS), store=SqlReceiptStore(database))
    objects = [
        make_object(
            "term-a", kind="term", label="derivative", content="the derivative of a function"
        ),
        make_object(
            "term-b",
            kind="term",
            label="differentiation",
            content="differentiation is the derivative of a function",
        ),
    ]
    report = resolve_relations(gateway, objects, course_id=CS)
    assert report.relations
    assert report.relations[0].relation == ALIAS
    assert report.relations[0].used_jev is True

    with database.connect() as connection:
        journey_status = connection.execute(
            "SELECT status FROM learning_journeys WHERE id='j1'"
        ).fetchone()[0]
        grade = connection.execute(
            "SELECT raw_score FROM assessment_sessions WHERE id='s1'"
        ).fetchone()[0]
        coverage = connection.execute("SELECT COUNT(*) FROM learning_coverage").fetchone()[0]
        receipts = connection.execute(
            "SELECT COUNT(*) FROM jev_decision_receipts"
        ).fetchone()[0]

    assert journey_status == "LEARNING"
    assert grade == 78.0
    assert coverage == 1
    assert receipts >= 1  # the only write was to the Jev receipt ledger
