# Knowledge granularity policy

Policy version: `compact-course-map-v1`

## Effective-node budget

Every effective course view has at most 50 unique stored nodes, including:

- COMPOSITE chapters;
- ATOMIC learning units;
- any explicitly stored course root;
- nodes contributed by an overlay, share snapshot, or automatic view after the
  effective view is materialized.

The limit is not pagination, CSS hiding, or truncation. A version cannot be
activated unless the entire source corpus is dispositioned against its final
bounded outline.

Typical courses should use 5–8 chapters and 20–36 learning units. Short courses
may use fewer. Fifty is a hard ceiling, not a target.

## Content preserved outside the node count

Source documents, chunks, locators, page ranges, examples, definitions,
conditions, method steps, misconceptions, questions, formulas, and citations
remain complete. They are evidence and instructional detail within a learning
unit, not additional navigation nodes.

Different algorithms, objects, or conflicting validity conditions must not be
merged merely to satisfy the count. Conversely, moving one hundred old micro
objectives unchanged into a single Spec does not count as compaction.

## Build order

1. Freeze the exact accessible source versions and reuse eligible prior paid
   artifacts.
2. Plan the whole-course outline and allocate the node budget once.
3. Map every readable teaching segment to one or more final ATOMIC units, or
   record an explicit reviewed/unsupported disposition.
4. Compile one concise, complete Teaching Spec for each final ATOMIC unit.
5. Validate node count, hierarchy, source coverage, permissions, version,
   provenance, and unresolved exceptions.
6. Activate the complete version atomically while the prior version stays
   available until the switch.

## History semantics

- One-to-one replacements may keep the original node ID.
- Many-to-one replacements require explicit lineage and an immutable mapping.
- Existing transcripts and Pairs are preserved; one Pair becomes primary and
  the others remain associated history. Conversations are never concatenated.
- A prior learning-start fact may remain visible as history.
- A merged unit becomes `LEARNED` only when its new REQUIRED objectives have
  valid coverage. One learned legacy micro-node cannot complete the whole unit.
- Historical grades are not averaged or rewritten into a new unit grade.
- An active assessment remains pinned to its original questions, Spec version,
  tree version, and grading contract until completion.

## Failure semantics

Empty courses produce `WAITING_SOURCE`, not fabricated chapters. Unreadable or
partially failed sources remain in the denominator and surface as explicit
exceptions. Provider failures retain receipts and retry identity; they are not
silently converted to success or removed from reconciliation.
