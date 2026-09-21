"""CourseEntityResolution: relate semantic objects inside a course — never merge.

Where it sits (deterministic-first chain)::

    permissions -> exact locator -> recall -> merge/dedupe -> relevance (rerank)
    -> condition/conflict check -> evidence pack -> generation

This module is a **relations-only** layer. Given a set of objects that the
deterministic backend has already authorized for one course/workspace — terms,
aliases, concepts, question variants, material versions, duplicate evidence — it
decides *how two of them relate*, and never changes any of them.

The split is fixed: **deterministic checks run first; Jev judges only the
residue.**

* **candidate generation is deterministic and scoped.** Pairs are produced only
  from the objects the caller passed (never a whole-database scan, never another
  user's private material) using, in order: exact id match, an existing accepted
  alias, title normalization, content hash, and a bounded local token similarity.
  Scope isolation is enforced twice: the caller supplies only in-scope objects,
  and the resolver filters on ``course_id`` as a backstop so an out-of-scope pair
  is never even offered.
* **exact duplicates cost zero Jev.** Byte-identical content is decided by a
  content hash in code (``SAME_CONCEPT``, ``used_jev=False``). Similarity is
  **not** proof of the same concept, and a relation is **never transitive by
  assumption**: A≈B and B≈C never silently relate A and C, and nothing is merged
  (the report has no cluster id — only pairwise relations).
* **Jev judges only the residue** through the catalog's ``entity.relation.v1``
  (Choice), one relation per pair, at most ``max_pairs`` semantic pairs per
  request; the pair budget and the number of unchecked pairs are recorded so a
  caller can never believe the whole corpus was compared.
* **relations only, never mutations.** A relation carries both original ids, the
  source versions, the evidence and a status; it never merges a knowledge node,
  deletes a user file, changes a publication record, or rewrites an official
  tree id, node binding, progress or mark.
* **query expansion is conservative.** At most a few *accepted* aliases are
  added, the user's original query is always preserved, and an explicit
  file/page/question target always outranks alias expansion (expansion is
  skipped, so the target is never displaced). Deduplication may fold duplicate
  evidence inside an evidence pack, but the file list and shared snapshots keep
  every valid file, and cross-user dedup never reveals that another user
  uploaded the same material.
* **degradation.** Jev unavailable / invalid / off / shadow / over budget returns
  ``UNCERTAIN`` (no relation), the original query is unchanged and retrieval is
  unaffected. The only table this module can write is ``jev_decision_receipts``
  (through the gateway's receipt store).

The decision definition is the catalog's own ``entity.relation.v1`` (already
registered in ``decision_catalog.json``) — this module never invents another id.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.jev.catalog import DecisionDefinition, load_catalog
from app.jev.errors import JevError
from app.jev.gateway import DecisionRequest, JevGateway
from app.jev.models import CacheScope, owner_scope_hash

# --------------------------------------------------------------------------- #
# Definition (registered in decision_catalog.json — never invent another id)
# --------------------------------------------------------------------------- #

ENTITY_RELATION_KEY = "entity.relation.v1"

# The seven Choice candidates of ``entity.relation.v1``.
SAME_CONCEPT = "SAME_CONCEPT"
ALIAS = "ALIAS"
QUESTION_VARIANT = "QUESTION_VARIANT"
DOCUMENT_VERSION_RELATION = "DOCUMENT_VERSION_RELATION"
RELATED_NOT_SAME = "RELATED_NOT_SAME"
DIFFERENT = "DIFFERENT"
UNCERTAIN = "UNCERTAIN"

RELATIONS = (
    SAME_CONCEPT,
    ALIAS,
    QUESTION_VARIANT,
    DOCUMENT_VERSION_RELATION,
    RELATED_NOT_SAME,
    DIFFERENT,
    UNCERTAIN,
)

# --------------------------------------------------------------------------- #
# Bounds
# --------------------------------------------------------------------------- #

# Jev sees at most this many semantic pairs per resolve request.
DEFAULT_MAX_PAIRS = 8

# At most this many accepted aliases may be added to a retrieval query.
DEFAULT_MAX_QUERY_ALIASES = 3

# Bounded per-object text sent to Jev for a pair comparison.
DEFAULT_MAX_OBJECT_CHARS = 2_000

# Bounded local token similarity threshold. Above it a pair is *offered* to Jev;
# similarity alone is never a relation (Jev may still say DIFFERENT / UNCERTAIN).
DEFAULT_SIMILARITY_THRESHOLD = 0.4

# Server-internal owner/authorization used when the caller does not supply a
# user-scoped :class:`CacheScope`. The digest is still server-derived (never
# client-supplied), so receipts never hit the ``owner_scope_hash`` NOT NULL
# constraint even for pipeline-internal decisions.
_ENTITY_RESOLUTION_OWNER = "entity-resolution"
_ENTITY_RESOLUTION_SCOPE = "entity-resolution"


def entity_relation_definition() -> DecisionDefinition:
    """The catalog's own ``entity.relation.v1`` definition."""
    return load_catalog().get(ENTITY_RELATION_KEY)


# --------------------------------------------------------------------------- #
# Normalization + bounded local similarity
# --------------------------------------------------------------------------- #

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]+|[\u4e00-\u9fff]+")

_STOPWORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "for", "with", "that", "this", "from", "are",
        "was", "were", "is", "be", "been", "being", "has", "have", "had", "not", "but",
        "will", "would", "should", "can", "could", "may", "might", "must", "than", "then",
        "also", "into", "over", "under", "between", "before", "after", "such", "these",
        "those", "they", "them", "their", "there", "here", "where", "when", "what",
        "which", "who", "how", "why", "you", "your", "it", "its", "as", "at", "by", "of",
        "on", "in", "to", "do", "does", "did", "all", "any", "each", "every", "some",
        "more", "most", "other", "only", "very", "just", "about", "above", "below",
        "example", "examples", "text", "content", "course", "material", "page", "pages",
        "section", "chapter", "question", "answer", "evidence", "source", "sources",
        "document", "file", "notes", "note",
    }
)


def normalize(value: str) -> str:
    """Fold case and collapse whitespace so two spellings of one label compare equal.

    This is a *candidate-generation* signal only: a normalized-title match makes a
    pair worth looking at; it is never by itself a SAME_CONCEPT verdict.
    """
    return " ".join((value or "").casefold().split())


def _tokens(text: str) -> frozenset[str]:
    found: set[str] = set()
    for token in _TOKEN.findall(text or ""):
        key = token.casefold()
        if key in _STOPWORDS:
            continue
        found.add(key)
        if len(found) >= 128:
            break
    return frozenset(found)


def local_similarity(left: str, right: str) -> float:
    """Token-set Jaccard over significant tokens (bounded, deterministic).

    Used only to *offer* a pair to Jev. Similarity is not proof of the same
    concept; the model still decides the relation (and may answer DIFFERENT).
    """
    a = _tokens(left)
    b = _tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# --------------------------------------------------------------------------- #
# The entity object
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class EntityObject:
    """One semantic object inside an authorized course/workspace scope.

    ``object_id`` is the stable backend id (knowledge-node id, term id, question
    id, material id, evidence id). ``aliases`` are already-*accepted* aliases the
    backend owns — a match there is authoritative and costs zero Jev.
    """

    object_id: str
    kind: str  # "term" | "concept" | "question" | "material" | "evidence"
    course_id: str
    material_revision: str
    label: str
    content: str = ""
    source_version: str | None = None
    aliases: tuple[str, ...] = ()

    def content_hash(self) -> str:
        """Stable sha256 of the exact content bytes (byte-identical => duplicate)."""
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CandidatePair:
    """One deterministic narrowing: a pair worth resolving, and why.

    ``deterministic_relation`` is set when the relation is decided in code
    (exact id / version / content hash / accepted alias) and costs zero Jev;
    ``None`` means the pair is semantic residue the model must judge.

    ``score`` is a deterministic strength used ONLY to order the candidate set
    (and to apply a pair cap order-independently). It is never a relation:
    deterministic pairs are ``None`` (they always rank first), ``title`` pairs are
    ``1.0`` and ``similarity`` pairs carry their Jaccard value.
    """

    left_id: str
    right_id: str
    reason: str  # exact_id | version | content_hash | alias | title | similarity
    deterministic_relation: str | None = None
    score: float | None = None


@dataclass(frozen=True)
class CandidatePairSet:
    """The scored, order-independent candidate set plus its cap accounting.

    ``scored`` is how many pairs passed classification *before* the cap;
    ``dropped_by_cap`` is how many of those were removed by ``max_candidate_pairs``
    (so a caller can never mistake a cap for "nothing else was comparable").
    ``pairs`` is always canonicalized (``left_id <= right_id``) and deterministically
    ordered, so the same object set yields the same pairs in any input order.
    """

    pairs: tuple[CandidatePair, ...]
    scored: int
    dropped_by_cap: int


@dataclass(frozen=True)
class EntityRelation:
    """The relation for one pair — a proposal only, never a mutation."""

    relation: str  # one of RELATIONS
    left_id: str
    right_id: str
    reason: str
    used_jev: bool
    receipt_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """A JSON-friendly projection the backend may persist verbatim."""
        return {
            "relation": self.relation,
            "left_id": self.left_id,
            "right_id": self.right_id,
            "reason": self.reason,
            "used_jev": self.used_jev,
            "receipt_id": self.receipt_id,
        }


@dataclass
class RelationReport:
    """Everything the caller needs to record relations — never a merge plan.

    ``unchecked_pairs`` + ``pair_budget`` make the un-compared residue explicit so
    a caller can never be led to believe the whole corpus was compared.
    ``excluded_out_of_scope`` names objects dropped before pairing (scope
    isolation backstop).
    """

    relations: list[EntityRelation] = field(default_factory=list)
    pair_budget: int = 0
    candidate_pairs: int = 0  # candidate pairs kept after the candidate cap
    dropped_by_cap: int = 0  # candidate pairs removed by max_candidate_pairs
    checked_pairs: int = 0  # relations produced (deterministic + semantic)
    semantic_pairs: int = 0  # pairs actually handed to Jev
    unchecked_pairs: int = 0  # semantic pairs skipped by the pair budget
    total_possible_pairs: int = 0  # n choose 2 over the in-scope set
    excluded_out_of_scope: tuple[str, ...] = ()

    @property
    def scored_pairs(self) -> int:
        """Candidate pairs that passed classification before the candidate cap."""
        return self.candidate_pairs + self.dropped_by_cap

    @property
    def merged_any(self) -> bool:
        """Always False: a relation never merges two objects."""
        return False

    @property
    def aliases(self) -> list[EntityRelation]:
        return [r for r in self.relations if r.relation == ALIAS]

    @property
    def duplicates(self) -> list[EntityRelation]:
        return [r for r in self.relations if r.reason == "content_hash"]

    @property
    def version_relations(self) -> list[EntityRelation]:
        return [r for r in self.relations if r.relation == DOCUMENT_VERSION_RELATION]


_ACCEPTED_NAME_SQL = (
    "SELECT node.title AS title, alias.alias AS alias "
    "FROM knowledge_node_aliases AS alias "
    "JOIN knowledge_nodes AS node ON node.id = alias.node_id "
    "WHERE node.course_id = ? AND ("
    "(node.owner_user_id = ? AND node.status = 'PRIVATE') OR "
    "(node.owner_user_id IS NULL AND node.status = 'PUBLISHED')) "
    "ORDER BY node.title, alias.normalized_alias, alias.locale"
)


def accepted_name_groups(
    database: object,
    course_id: str,
    subject: str,
) -> tuple[tuple[str, ...], ...]:
    """The accepted names of one course's concepts, scoped to this subject.

    One group per knowledge node: its canonical title first, then its
    already-accepted aliases. Only rows the subject is actually allowed to see are
    returned — its own private nodes, plus published official nodes — so another
    learner's private vocabulary can never widen this subject's query. Returns
    ``()`` when the registry is unavailable, which leaves the query un-expanded.
    """
    try:
        with database.connect() as connection:  # type: ignore[attr-defined]
            rows = connection.execute(_ACCEPTED_NAME_SQL, (course_id, subject)).fetchall()
    except Exception:  # pragma: no cover - the registry is optional for retrieval
        return ()
    groups: dict[str, list[str]] = {}
    for row in rows:
        title = str(row["title"] or "").strip()
        alias = str(row["alias"] or "").strip()
        if not title or not alias:
            continue
        names = groups.setdefault(title, [])
        if alias not in names:
            names.append(alias)
    return tuple((title, *names) for title, names in groups.items())


@dataclass(frozen=True)
class ExpandedQuery:
    """The result of conservative alias expansion (retrieval input)."""

    original_query: str
    expanded_query: str
    added_aliases: tuple[str, ...]
    skipped_because_explicit_target: bool
    # Canonical terms whose name group the query matched, so the caller can record
    # *why* a query was expanded instead of inferring it from the string diff.
    matched_groups: tuple[str, ...] = ()


# --------------------------------------------------------------------------- #
# Query expansion (deterministic; never reaches Jev)
# --------------------------------------------------------------------------- #


def expand_query(
    query: str,
    *,
    name_groups: Sequence[Sequence[str]] = (),
    explicit_targets: Sequence[str] = (),
    max_aliases: int = DEFAULT_MAX_QUERY_ALIASES,
) -> ExpandedQuery:
    """Add the other accepted names of a concept the query already names.

    ``name_groups`` is one group per concept: the backend-owned canonical term
    first, then that concept's already-accepted aliases. A group is only used when
    the query itself names one of its members, so a Chinese question about "密度聚类"
    can gain "DBSCAN" while an unrelated question in the same course gains nothing —
    expansion never injects a course-wide alias list into every query, which would
    hurt precision and spend retrieval budget on terms the learner never asked
    about. The canonical term is also added back when only an alias was used, so the
    mapping works in both directions.

    The user's original query is always the prefix and is never removed. An explicit
    file/page/question target always outranks expansion: when one is present,
    expansion is skipped entirely so the target can never be displaced. Names that
    already appear in the query are skipped so the query is never duplicated.
    """
    original = (query or "").strip()
    if not original:
        return ExpandedQuery(original, original, (), False)
    if explicit_targets:
        return ExpandedQuery(original, original, (), True)

    added: list[str] = []
    matched: list[str] = []
    folded_original = original.casefold()
    for group in name_groups:
        names: list[str] = []
        for candidate in group:
            text = str(candidate or "").strip()
            if text and text not in names:
                names.append(text)
        if not names:
            continue
        folded = [name.casefold() for name in names]
        # The query must name this concept before any of its other names are added.
        if not any(name in folded_original for name in folded):
            continue
        matched.append(names[0])
        for name, folded_name in zip(names, folded, strict=True):
            if len(added) >= max(0, max_aliases):
                break
            if folded_name in folded_original:
                continue  # already present; never duplicate the original
            added.append(name)

    if not added:
        return ExpandedQuery(original, original, (), False)
    return ExpandedQuery(
        original,
        f"{original} {' '.join(added)}",
        tuple(added),
        False,
        tuple(matched),
    )


# --------------------------------------------------------------------------- #
# Candidate generation (deterministic, scoped, zero Jev)
# --------------------------------------------------------------------------- #


def _is_accepted_alias(left: EntityObject, right: EntityObject) -> bool:
    """True when one object's label/id is an already-accepted alias of the other."""
    left_keys = {normalize(alias) for alias in left.aliases}
    right_keys = {normalize(alias) for alias in right.aliases}
    left_label = normalize(left.label)
    right_label = normalize(right.label)
    left_id = normalize(left.object_id)
    right_id = normalize(right.object_id)
    return (
        (bool(right_label) and right_label in left_keys)
        or (bool(right_id) and right_id in left_keys)
        or (bool(left_label) and left_label in right_keys)
        or (bool(left_id) and left_id in right_keys)
    )


def _classify_pair(
    left: EntityObject, right: EntityObject, *, similarity_threshold: float
) -> CandidatePair | None:
    """Classify one pair deterministically, in priority order, or drop it."""
    # 1. Same backend id: same object (or two revisions of it).
    if left.object_id == right.object_id:
        if left.material_revision != right.material_revision:
            return CandidatePair(
                left.object_id, right.object_id, "version", DOCUMENT_VERSION_RELATION
            )
        return CandidatePair(left.object_id, right.object_id, "exact_id", SAME_CONCEPT)

    # 2. Byte-identical content (non-empty): duplicate evidence, decided by hash.
    if left.content and right.content and left.content_hash() == right.content_hash():
        return CandidatePair(left.object_id, right.object_id, "content_hash", SAME_CONCEPT)

    # 3. Already-accepted alias: authoritative, zero Jev.
    if _is_accepted_alias(left, right):
        return CandidatePair(left.object_id, right.object_id, "alias", ALIAS)

    # 4. Title normalization: same normalized label -> semantic residue.
    left_label = normalize(left.label)
    right_label = normalize(right.label)
    if left_label and left_label == right_label:
        return CandidatePair(left.object_id, right.object_id, "title", None, 1.0)

    # 5. Bounded local similarity: offer to Jev; similarity is not a verdict.
    similarity = local_similarity(
        f"{left.label} {left.content}", f"{right.label} {right.content}"
    )
    if similarity >= similarity_threshold:
        return CandidatePair(left.object_id, right.object_id, "similarity", None, similarity)

    return None


def _canonical_pair(pair: CandidatePair) -> CandidatePair:
    """Return the pair with ids in canonical (``left_id <= right_id``) order.

    The relation is unordered, so a candidate must not depend on which object the
    caller happened to place first.
    """
    if pair.left_id <= pair.right_id:
        return pair
    return CandidatePair(
        pair.right_id, pair.left_id, pair.reason, pair.deterministic_relation, pair.score
    )


def _candidate_sort_key(pair: CandidatePair) -> tuple[int, float, str, str]:
    """A total, order-independent sort key for the candidate set.

    Deterministic pairs first, then strongest score, then canonical ids — so the
    capped (and Jev-budgeted) subset never depends on the caller's input order.
    """
    priority = 0 if pair.deterministic_relation is not None else 1
    return (priority, -(pair.score if pair.score is not None else 0.0), pair.left_id, pair.right_id)


def generate_candidate_pairs(
    objects: Sequence[EntityObject],
    *,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    max_candidate_pairs: int | None = None,
) -> CandidatePairSet:
    """Deterministically narrow an already-authorized in-scope set into pairs.

    Every unordered pair is scored symmetrically (the same two objects produce the
    same pair whichever is ``left``), canonicalized, sorted by a stable key, and —
    when ``max_candidate_pairs`` is set — capped *after* scoring so the cap is
    order-independent. Pairs are pairwise only, never a transitive closure, and the
    set is the caller-bounded authorized scope — this function never reaches the
    database.
    """
    scored: list[CandidatePair] = []
    for i in range(len(objects)):
        for j in range(i + 1, len(objects)):
            pair = _classify_pair(objects[i], objects[j], similarity_threshold=similarity_threshold)
            if pair is not None:
                scored.append(_canonical_pair(pair))
    scored.sort(key=_candidate_sort_key)

    cap = None if max_candidate_pairs is None else max(0, max_candidate_pairs)
    total = len(scored)
    if cap is not None and total > cap:
        kept = scored[:cap]
        dropped = total - cap
    else:
        kept = scored
        dropped = 0
    return CandidatePairSet(pairs=tuple(kept), scored=total, dropped_by_cap=dropped)


# --------------------------------------------------------------------------- #
# Resolution (deterministic first, Jev on the residue)
# --------------------------------------------------------------------------- #


def _object_view(obj: EntityObject, max_chars: int) -> dict[str, Any]:
    """The bounded view of one object Jev may see (never the whole corpus)."""
    return {
        "kind": obj.kind,
        "label": obj.label[:max_chars],
        "content": obj.content[:max_chars],
        "source_version": obj.source_version,
    }


def _judge_pair(
    gateway: JevGateway | None,
    left: EntityObject | None,
    right: EntityObject | None,
    *,
    course_id: str,
    material_revision: str,
    cache_scope: CacheScope,
    max_object_chars: int,
) -> tuple[str, bool, str | None]:
    """Run ``entity.relation.v1`` over one pair's residue; never a mutation."""
    if gateway is None or left is None or right is None:
        return UNCERTAIN, False, None

    definition = entity_relation_definition()
    request = DecisionRequest(
        definition=definition,
        state={
            "left": _object_view(left, max_object_chars),
            "right": _object_view(right, max_object_chars),
            "course_id": course_id,
            "material_revision": material_revision,
        },
        caller_role="entity_resolution",
        cache_scope=cache_scope,
        criteria=dict(definition.criteria or {}),
        instructions=definition.instructions,
    )
    try:
        decision = gateway.evaluate(request)
    except JevError:
        return UNCERTAIN, False, None

    suggestion = decision.suggestion
    if (
        decision.mode == "on"
        and suggestion is not None
        and suggestion.choice is not None
        and suggestion.choice in RELATIONS
    ):
        return suggestion.choice, True, decision.receipt_id
    return UNCERTAIN, False, decision.receipt_id


def resolve_relations(
    gateway: JevGateway | None,
    objects: Sequence[EntityObject],
    *,
    course_id: str,
    material_revision: str = "",
    cache_scope: CacheScope | None = None,
    max_pairs: int = DEFAULT_MAX_PAIRS,
    max_candidate_pairs: int | None = None,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    max_object_chars: int = DEFAULT_MAX_OBJECT_CHARS,
) -> RelationReport:
    """Relate the semantic objects inside one course; never merge any of them.

    ``objects`` are already-authorized in-scope objects; as a backstop any object
    whose ``course_id`` differs is dropped before pairing and named in
    ``excluded_out_of_scope``. Deterministic pairs (exact id / version / content
    hash / accepted alias) are resolved in code with zero Jev; semantic pairs
    (title / similarity) are handed to Jev at most ``max_pairs`` times, and the
    rest are recorded in ``unchecked_pairs``. Candidate generation is symmetric and
    order-independent; when ``max_candidate_pairs`` is set, the cap is applied after
    scoring and the dropped count is recorded in ``dropped_by_cap``.
    """
    in_scope = [obj for obj in objects if obj.course_id == course_id]
    excluded = tuple(sorted({obj.object_id for obj in objects if obj.course_id != course_id}))

    report = RelationReport(
        pair_budget=max(0, max_pairs),
        total_possible_pairs=len(in_scope) * (len(in_scope) - 1) // 2,
        excluded_out_of_scope=excluded,
    )

    pair_set = generate_candidate_pairs(
        in_scope,
        similarity_threshold=similarity_threshold,
        max_candidate_pairs=max_candidate_pairs,
    )
    pairs = pair_set.pairs
    report.candidate_pairs = len(pairs)
    report.dropped_by_cap = pair_set.dropped_by_cap

    by_id = {obj.object_id: obj for obj in in_scope}
    scope = cache_scope or CacheScope(
        owner_scope_hash=owner_scope_hash(_ENTITY_RESOLUTION_OWNER, _ENTITY_RESOLUTION_SCOPE),
        course_id=course_id,
        material_revision=material_revision or None,
    )

    semantic_used = 0
    unchecked = 0
    for pair in pairs:
        if pair.deterministic_relation is not None:
            report.relations.append(
                EntityRelation(
                    relation=pair.deterministic_relation,
                    left_id=pair.left_id,
                    right_id=pair.right_id,
                    reason=pair.reason,
                    used_jev=False,
                    receipt_id=None,
                )
            )
            continue
        if semantic_used >= report.pair_budget:
            unchecked += 1
            continue
        semantic_used += 1
        relation, used, receipt = _judge_pair(
            gateway,
            by_id.get(pair.left_id),
            by_id.get(pair.right_id),
            course_id=course_id,
            material_revision=material_revision,
            cache_scope=scope,
            max_object_chars=max_object_chars,
        )
        report.relations.append(
            EntityRelation(
                relation=relation,
                left_id=pair.left_id,
                right_id=pair.right_id,
                reason=pair.reason,
                used_jev=used,
                receipt_id=receipt,
            )
        )

    report.checked_pairs = len(report.relations)
    report.semantic_pairs = semantic_used
    report.unchecked_pairs = unchecked
    return report


class CourseEntityResolver:
    """Thin, bound-injected wrapper over :func:`resolve_relations` / :func:`expand_query`."""

    def __init__(
        self,
        gateway: JevGateway | None = None,
        *,
        max_pairs: int = DEFAULT_MAX_PAIRS,
        max_candidate_pairs: int | None = None,
        max_aliases: int = DEFAULT_MAX_QUERY_ALIASES,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
        max_object_chars: int = DEFAULT_MAX_OBJECT_CHARS,
    ) -> None:
        self.gateway = gateway
        self.max_pairs = max_pairs
        self.max_candidate_pairs = max_candidate_pairs
        self.max_aliases = max_aliases
        self.similarity_threshold = similarity_threshold
        self.max_object_chars = max_object_chars

    def resolve(
        self,
        objects: Sequence[EntityObject],
        *,
        course_id: str,
        material_revision: str = "",
        cache_scope: CacheScope | None = None,
    ) -> RelationReport:
        return resolve_relations(
            self.gateway,
            objects,
            course_id=course_id,
            material_revision=material_revision,
            cache_scope=cache_scope,
            max_pairs=self.max_pairs,
            max_candidate_pairs=self.max_candidate_pairs,
            similarity_threshold=self.similarity_threshold,
            max_object_chars=self.max_object_chars,
        )

    def expand_query(
        self,
        query: str,
        *,
        name_groups: Sequence[Sequence[str]] = (),
        explicit_targets: Sequence[str] = (),
    ) -> ExpandedQuery:
        return expand_query(
            query,
            name_groups=name_groups,
            explicit_targets=explicit_targets,
            max_aliases=self.max_aliases,
        )


__all__ = [
    "ALIAS",
    "CandidatePair",
    "CandidatePairSet",
    "CourseEntityResolver",
    "DEFAULT_MAX_OBJECT_CHARS",
    "DEFAULT_MAX_PAIRS",
    "DEFAULT_MAX_QUERY_ALIASES",
    "DEFAULT_SIMILARITY_THRESHOLD",
    "DIFFERENT",
    "DOCUMENT_VERSION_RELATION",
    "ENTITY_RELATION_KEY",
    "EntityObject",
    "EntityRelation",
    "ExpandedQuery",
    "QUESTION_VARIANT",
    "RELATED_NOT_SAME",
    "RELATIONS",
    "RelationReport",
    "SAME_CONCEPT",
    "UNCERTAIN",
    "accepted_name_groups",
    "entity_relation_definition",
    "expand_query",
    "generate_candidate_pairs",
    "local_similarity",
    "normalize",
    "resolve_relations",
]
