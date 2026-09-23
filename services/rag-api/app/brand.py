"""The single brand and URL source for the backend.

Task A1 asks for one configuration source — English name, Chinese name, canonical and API
origins, logo path, support name — that documents, manifest and templates read instead of each
place repeating the product name. `apps/web/src/brand.ts` is that source for the web app; this is
its backend counterpart, so the FastAPI titles, the tutor persona and the default display name
stop being literals scattered across modules.

What is deliberately **not** here: compatibility identifiers. `cmui_*` tables, `CMUI_*` variables,
`window.CourseMateAuth`, `window.CourseMateMath`, the internal `X-CourseMate-Internal-Token`
header, and the `coursemate_*` version identifiers inside stored template/definition names all
keep their spelling because callers and saved data depend on them. They are listed in
`COMPATIBILITY_IDENTIFIERS` so a guard can require that a rename leaves them alone — renaming them
is a separate, dual-named migration (see `docs/coursejesus/BRAND_REPLACEMENT_MATRIX.md`, class B).

The two name values are asserted consistent by `tests/test_brand_identity.py`: this module may not
contain the previous product name, and neither may the user-visible surfaces built from it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

# The name this product replaced. Kept as a value rather than a literal in the guard so the guard
# and any future migration read it from one place.
PREVIOUS_NAME: Final = "CourseMate"


@dataclass(frozen=True)
class ApiOrigins:
    rag: str
    agent: str


@dataclass(frozen=True)
class Brand:
    name: str
    name_zh: str
    tagline: str
    canonical_origin: str
    www_origin: str
    api_origins: ApiOrigins
    previous_origins: tuple[str, ...]
    logo_path: str
    logo_status: str
    theme_color: str
    support_name: str
    support_email: str | None

    def title(self, section: str = "") -> str:
        return f"{self.name} · {section}" if section else self.name

    def zh_title(self, section: str = "") -> str:
        return f"{self.name} {section}" if section else self.name

    def default_display_name(self) -> str:
        """What a user is called until they set a name: the product, then 同学."""
        return f"{self.name} 同学"

    def canvas_callback_url(self) -> str:
        """The OAuth callback the Canvas integration is registered against."""
        return f"{self.api_origins.rag}/api/integrations/canvas/oauth/callback"


BRAND: Final = Brand(
    name="CourseJesus",
    name_zh="耶课稣",
    tagline="Grounded answers. Accountable actions.",
    canonical_origin="https://coursejesus.com",
    www_origin="https://www.coursejesus.com",
    api_origins=ApiOrigins(
        rag="https://rag.coursejesus.com",
        agent="https://agent.coursejesus.com",
    ),
    previous_origins=(
        "https://qqttai.com",
        "https://www.qqttai.com",
        "https://rag.qqttai.com",
        "https://agent.qqttai.com",
    ),
    logo_path="/favicon.svg",
    # No artwork has been supplied. Saying PENDING_ASSET is the honest state; inventing a final
    # mark, or silently shipping the interim one as if it were the owner's, is not.
    logo_status="PENDING_ASSET",
    theme_color="#0d4637",
    support_name="CourseJesus support",
    support_email=None,
)

# Internal contracts that must survive any future rename, with the reason they are kept. The guard
# test asserts each one is still present where it is used, so a rename cannot quietly drop them.
COMPATIBILITY_IDENTIFIERS: Final[tuple[str, ...]] = (
    "cmui_users",
    "cmui_",
    "CMUI_",
    "CourseMateAuth",
    "CourseMateMath",
    "CourseMateUi",
    "CourseMateApp",
    "X-CourseMate-Internal-Token",
    # The same header in its two other spellings: the Python parameter name in the tool-intent
    # route (from which FastAPI derives the wire name) and the bare form the matcher sees inside
    # it. Found by the guard in `tests/test_brand_identity.py`, which refuses an old-name
    # identifier nobody recorded.
    "x_coursemate_internal_token",
    "coursemate_internal_token",
    "coursemate_response",
    "coursemate_exercise_v",
    "coursemate_assessment_reference_v",
    "coursemate_classification_v",
)


def previous_name_variants() -> tuple[str, ...]:
    """Spellings of the old name that a visible surface must not use."""
    return (PREVIOUS_NAME, PREVIOUS_NAME.upper(), PREVIOUS_NAME.lower())
