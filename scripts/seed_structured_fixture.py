#!/usr/bin/env python3
"""Seed the synthetic content the structured-module journeys act on.

Four browser journeys — alias retrieval, same word in two senses, a condition
difference, and an unsupported citation — cannot run on the prepared E2E database
as it was: that database has real course material, but none of it is *shaped* for
those modules. This fixture adds the shape, and nothing else:

* three English-only pages for the alias and same-word journeys, so a Chinese
  question can only reach the English page through an accepted alias, and one word
  ("kernel") is deliberately used in two unrelated senses;
* two pages stating the same quantity under *different* assumptions, and two
  stating it under the *same* assumption with different values — the condition
  difference and the genuine contradiction module C has to tell apart;
* one published concept with an accepted English alias (the registry row the
  deterministic query expansion reads).

Documents are ingested through the product's own `IngestionService`, so chunks,
the FTS index, the embeddings and the source-version rows are exactly what the
running service will read — the fixture never hand-writes a chunk row.

It must never run against anything outside `work/`, and it is idempotent: a second
run against the same file adds nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "rag-api"))

from app.config import Settings  # noqa: E402 - repository-local service bootstrap
from app.db import Database  # noqa: E402 - repository-local service bootstrap
from app.learning.workspaces import join_course  # noqa: E402
from app.rag.embeddings import DeterministicEmbeddingProvider  # noqa: E402
from app.services.ingestion import IngestionService  # noqa: E402

COURSE_ID = "cs3481"
WORK_ROOT = ROOT / "work"

# The English-only page the Chinese concept must reach. It names DBSCAN and never
# the Chinese term, so a lexical hit on it can only come from alias expansion.
ALIAS_PAGE = "e2e_density_clustering_en.txt"
# One word, two unrelated senses.
KERNEL_SVM_PAGE = "e2e_kernel_svm_en.txt"
KERNEL_OS_PAGE = "e2e_kernel_os_en.txt"
# The same quantity under the *same* assumption with two different values: a
# genuine contradiction, not a scope difference. `5%` is also the figure the
# supported-citation control asks about.
ALPHA_TWO_SIDED_A_PAGE = "e2e_alpha_two_sided_a.txt"
ALPHA_TWO_SIDED_B_PAGE = "e2e_alpha_two_sided_b.txt"
# The same quantity under a *different* assumption: a scope difference module C
# must not report as a contradiction.
ALPHA_ONE_SIDED_PAGE = "e2e_alpha_one_sided.txt"
# One document, two sections, one quantity with two values. Markdown is deliberate:
# the loader gives each heading its own section and locator
# (`app/rag/loaders.py::_load_markdown`), so the two fragments land in *different
# chunks of the same document* — which is what module C's deterministic narrowing
# reports as a version/task difference, in code and with no model call.
THRESHOLD_SECTIONS_PAGE = "e2e_threshold_sections.md"
# A page whose questions are explicitly numbered, so `parse_query_reference` can name
# one and the structured search can filter on it (`app/rag/structure.py` reads
# "Question N" and a following "(b)"). This is the exact locator the "a question
# number is never replaced by a semantic ranking" journey leans on: without content
# that really carries question metadata, that journey could only assert the parser's
# output, never the retrieval that depends on it.
LOCATOR_PAGE = "e2e_locator_questions.txt"
# One document, two sections, one quantity with two values. Markdown is deliberate:
# the loader gives each heading its own section and locator
# (`app/rag/loaders.py::_load_markdown`), so the two fragments land in *different
# chunks of the same document* — which is what module C's deterministic narrowing
# reports as a version/task difference, in code and with no model call.
THRESHOLD_SECTIONS_PAGE = "e2e_threshold_sections.md"

# Every figure below is written with a unit the deterministic layer-2 check reads
# (`app/jev/citation_audit.py::_NUMBER`: percent/%/percentage points/km/… — a bare
# integer is deliberately not treated as a falsifiable assertion). A journey can
# therefore ask about a figure no page states and get a code-decided verdict with
# zero model calls, and ask about one that a page *does* state and get none.
DOCUMENTS: tuple[tuple[str, str], ...] = (
    (
        ALIAS_PAGE,
        (
            "Density-based clustering with DBSCAN\n\n"
            "DBSCAN groups samples that are closely packed together and marks samples in\n"
            "low-density regions as noise. Two parameters control the result: the\n"
            "neighbourhood radius eps and the minimum number of points MinPts. The method\n"
            "does not need a preset number of clusters.\n"
        ),
    ),
    (
        KERNEL_SVM_PAGE,
        (
            "The kernel trick in support vector machines\n\n"
            "In a support vector machine the kernel function maps samples into a\n"
            "higher-dimensional feature space, so a linear separator can be found without\n"
            "computing the mapping explicitly. The worked example uses a polynomial kernel\n"
            "of degree three.\n"
        ),
    ),
    (
        KERNEL_OS_PAGE,
        (
            "The operating system kernel\n\n"
            "An operating system kernel manages processes, memory and device drivers. Its\n"
            "scheduler decides which process runs next, and a system call is the only way a\n"
            "user program may ask the kernel to act on its behalf.\n"
        ),
    ),
    (
        ALPHA_TWO_SIDED_A_PAGE,
        (
            "The default significance level, first source\n\n"
            "For a two-sided test the default significance level of alpha is 5%.\n"
        ),
    ),
    (
        ALPHA_TWO_SIDED_B_PAGE,
        (
            "The default significance level, second source\n\n"
            "For a two-sided test the default significance level of alpha is 20%.\n"
        ),
    ),
    (
        ALPHA_ONE_SIDED_PAGE,
        (
            "The default significance level under a one-sided test\n\n"
            "For a one-sided test the default significance level of alpha is 10%.\n"
        ),
    ),
    (
        THRESHOLD_SECTIONS_PAGE,
        (
            "# Decision threshold for the univariate case\n\n"
            "In the univariate case the decision threshold used by the worked example of\n"
            "this section is 3.5%.\n\n"
            "# Decision threshold for the multivariate case\n\n"
            "In the multivariate case the decision threshold used by the worked example of\n"
            "this section is 8.2%.\n"
        ),
    ),
    (
        LOCATOR_PAGE,
        (
            "Practice questions for this course\n\n"
            "Question 3\n\n"
            "(a) State the two parameters that a density-based method needs.\n\n"
            "(b) Explain what changes when the minimum number of points is increased.\n\n"
            "Question 4\n\n"
            "(a) Define the neighbourhood radius.\n"
        ),
    ),
)

# (node id, canonical title, description, major, accepted aliases)
NODES: tuple[tuple[str, str, str, str, tuple[str, ...]], ...] = (
    (
        "e2e-node-density-clustering",
        "\u5bc6\u5ea6\u805a\u7c7b",
        "Synthetic concept for the alias-retrieval journey",
        "CS",
        ("DBSCAN", "density-based clustering"),
    ),
)


def _require_course(database: Database) -> None:
    """The fixture attaches to a course that already exists; it never creates one.

    Creating a course here would mean this script could be the thing that decided a
    course's identity. The prepared E2E database is a copy of the local one and
    already carries `cs3481`; if it does not, saying so is better than inventing one.
    """
    with database.connect() as connection:
        row = connection.execute(
            "SELECT id FROM courses WHERE id = ?", (COURSE_ID,)
        ).fetchone()
    if row is None:
        raise RuntimeError(
            f"{COURSE_ID} is not in this database; the structured fixture attaches to an "
            "existing course rather than creating one"
        )


def seed_structured_fixture(
    db: Database, settings: Settings, owner: str
) -> dict[str, list[str]]:
    """Ingest the fixture pages into the owner's workspace and register the alias.

    The pages go into the learner's own workspace corpus rather than the official
    course. That is not a convenience: the real `cs3481` in this database is under
    publication review, and the product's own ingestion **refused** the write
    ("Course content is locked by publication review") — which is the guardrail
    working. The workspace corpus is the honest place for material a learner added
    for themselves, and it is retrieved through the same authorized private scope
    the shipping product uses.
    """

    service = IngestionService(db, settings, DeterministicEmbeddingProvider())
    _require_course(db)
    workspace = join_course(db, COURSE_ID, owner, 10)
    corpus = str(workspace["private_course_id"])
    ingested: list[str] = []
    with db.connect() as connection:
        existing = {
            str(row["filename"])
            for row in connection.execute(
                "SELECT filename FROM documents WHERE course_id = ?", (corpus,)
            ).fetchall()
        }
    for filename, body in DOCUMENTS:
        if filename in existing:
            continue
        accepted = service.queue_document(
            course_id=corpus,
            filename=filename,
            media_type="text/plain",
            content=body.encode("utf-8"),
            owner_user_id=owner,
            is_admin=False,
        )
        service.process_document(accepted.document.id, accepted.job.id)
        status = service.get_document(accepted.document.id).status.value
        if status != "ready":
            raise RuntimeError(f"{filename} did not reach ready: {status}")
        ingested.append(filename)

    with db.connect() as connection:
        for node_id, title, description, major, aliases in NODES:
            connection.execute(
                "INSERT OR IGNORE INTO knowledge_nodes("
                "id,course_id,owner_user_id,title,description,major,kind,status) "
                "VALUES(?,?,NULL,?,?,?,'ATOMIC','PUBLISHED')",
                (node_id, COURSE_ID, title, description, major),
            )
            for alias in aliases:
                connection.execute(
                    "INSERT OR IGNORE INTO knowledge_node_aliases("
                    "node_id,alias,normalized_alias,locale) VALUES(?,?,?,?)",
                    (node_id, alias, alias.casefold(), "en"),
                )
    return {"ingested": ingested, "documents": [name for name, _ in DOCUMENTS]}


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: seed_structured_fixture.py DATABASE_PATH [OWNER]")
    target = Path(sys.argv[1]).resolve()
    # The E2E flow hands over the database `prepare_full_e2e.py` already built;
    # opening it directly keeps one shared file for the server and every seeder.
    if not target.is_file() or WORK_ROOT not in target.parents:
        raise ValueError("An existing database file under work/ is required")
    settings = Settings(
        database_path=target,
        upload_dir=target.parent / "uploads",
        v3_enabled=True,
    )
    owner = sys.argv[2] if len(sys.argv) > 2 else "e2e-owner"
    result = seed_structured_fixture(Database(settings), settings, owner)
    print(
        f"Seeded the structured-module fixture: {len(result['ingested'])} new "
        f"document(s) of {len(result['documents'])}."
    )


if __name__ == "__main__":
    main()
