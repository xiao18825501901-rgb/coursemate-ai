"""Local campus catalog growth is **CLOSED** — the final batch was frozen on 2026-09-24.

"Growth" means exactly two things, and this module guards both:

* **discovery** — walking the local source roots (`D:\\Canvas`, `D:\\Canvas-DG`) to find files
  that are not already in the frozen batch (`scripts/scan_campus_inventory.py`);
* **ingestion** — turning source files into courses, documents and chunks
  (`app/campus_ingestion.py::ingest_course`, `scripts/ingest_campus_course.py`).

Everything else the product does is deliberately **not** growth and never consults this module:
reading existing campus courses, teaching, question answering, private uploads, the user's own
Canvas private import, backups, migrations and the test suites. The closure record is
`CAMPUS_FINAL_BATCH_CLOSURE.md` and its frozen `CAMPUS_FINAL_BATCH_MANIFEST.json`.

Why the switch is fail-closed: the batch is closed, so a run that forgets to set the variable must
**not** silently reopen it. Unset therefore means `PAUSED`. Reopening is a user decision and is
expressed as `CMUI_CAMPUS_CATALOG_GROWTH=open` — the same explicit style as `JEV_DEFINITION_MODES`,
which refuses an unknown value rather than ignoring it, because a misspelled value that silently
keeps the gate open (or closed) is the hardest kind of state to notice from the outside.
"""

from __future__ import annotations

import os
from typing import Final

CAMPUS_CATALOG_GROWTH_ENV: Final = "CMUI_CAMPUS_CATALOG_GROWTH"
OPEN: Final = "open"
PAUSED: Final = "paused"
GROWTH_STATUSES: Final = (OPEN, PAUSED)

# The state the project is in: the final batch was frozen and the local expansion path closed.
DEFAULT_GROWTH_STATUS: Final = PAUSED

CLOSURE_RECORD: Final = "CAMPUS_FINAL_BATCH_CLOSURE.md"
CLOSURE_MANIFEST: Final = "CAMPUS_FINAL_BATCH_MANIFEST.json"


class CampusCatalogGrowthPaused(RuntimeError):
    """Raised when a growth path is invoked while the local campus catalog is closed."""


def growth_status() -> str:
    """The effective growth status: the env var when set, otherwise the shipped `PAUSED`."""
    raw = (os.environ.get(CAMPUS_CATALOG_GROWTH_ENV) or "").strip().lower()
    if not raw:
        return DEFAULT_GROWTH_STATUS
    if raw not in GROWTH_STATUSES:
        raise ValueError(
            f"{CAMPUS_CATALOG_GROWTH_ENV} must be one of {sorted(GROWTH_STATUSES)}, got {raw!r}. "
            "An unknown value is refused rather than ignored: guessing here either grows the "
            "campus catalog after it was frozen, or blocks a run the operator believes is open."
        )
    return raw


def growth_is_open() -> bool:
    return growth_status() == OPEN


def require_growth_open(action: str) -> None:
    """Refuse a growth action while the catalog is closed, naming the closure record."""
    if growth_is_open():
        return
    raise CampusCatalogGrowthPaused(
        f"Refusing to {action}: local campus catalog growth is {DEFAULT_GROWTH_STATUS.upper()} "
        f"(the final batch was frozen; see {CLOSURE_RECORD} and {CLOSURE_MANIFEST}). "
        f"Set {CAMPUS_CATALOG_GROWTH_ENV}=open only as an explicit decision to start a new batch; "
        "existing campus courses, private uploads and Canvas imports are unaffected by this gate."
    )
