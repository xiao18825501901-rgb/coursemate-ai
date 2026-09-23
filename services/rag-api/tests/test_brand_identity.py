"""The backend brand identity: one source, no old visible name, and the contracts left alone.

Task A1's rename is only finished when a visible old name cannot come back and the compatibility
identifiers cannot be removed by accident. This suite pins both halves:

* the brand source carries the new name and origins, and contains no old name;
* the user-visible surfaces are **built from** that source rather than repeating a literal;
* the compatibility identifiers (`cmui_*`, `CMUI_*`, `window.CourseMateAuth`,
  `coursemate_*` version names, the internal token header) are still present where callers and
  stored data depend on them — the pack requires them kept, and a rename that "cleans" them would
  break running installations.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

from app.brand import BRAND, COMPATIBILITY_IDENTIFIERS, PREVIOUS_NAME, previous_name_variants

SERVICE = pathlib.Path(__file__).resolve().parents[1]
APP = SERVICE / "app"

# The surfaces that must read the brand source. Each entry is (path, what a user sees there).
VISIBLE_SURFACES = (
    ("app/rag/prompt.py", "the tutor persona a student's answers come from"),
    ("app/cm_update/provider.py", "the Chinese teacher instruction"),
    ("app/cm_update/auth.py", "the default display name"),
    ("app/cm_update/directory.py", "the default display name in the directory"),
    ("app/cm_update/social.py", "the default display name in a new conversation"),
    ("app/main.py", "the RAG API title"),
    ("app/cm_update/app.py", "the UI API title"),
    ("app/cm_update/db.py", "a developer-facing guard message"),
    ("app/cm_update/qualification_snapshot.py", "a developer-facing guard message"),
    ("app/evaluation/deepseek_canary.py", "the canary's own persona line"),
    ("app/evaluation/agent_tool_benchmark.py", "the agent benchmark's persona line"),
)

# A line may keep the old spelling only when it carries one of these contracts.
ALLOWED_ON_A_LINE = COMPATIBILITY_IDENTIFIERS + (
    "coursejesus",
    "CourseJesus",
    # A credential *default*, not a brand string: the dev-only fallback verification secret, kept
    # so locally issued verification tokens stay valid across restarts. Renaming it would
    # invalidate them, and production requires CMUI_VERIFICATION_SECRET anyway.
    "coursemate-dev-verification-secret",
    # A machine value in the UI service's status payload. A client that keys on it would break if
    # it changed, so it is a contract rather than a visible name.
    "coursemate-ui-update",
)


def test_the_brand_source_carries_the_new_identity_and_no_old_name() -> None:
    assert BRAND.name == "CourseJesus"
    assert BRAND.name_zh == "耶课稣"
    assert BRAND.canonical_origin == "https://coursejesus.com"
    assert BRAND.www_origin == "https://www.coursejesus.com"
    assert BRAND.api_origins.rag == "https://rag.coursejesus.com"
    assert BRAND.api_origins.agent == "https://agent.coursejesus.com"
    assert BRAND.logo_status == "PENDING_ASSET", "no artwork exists; do not claim a final mark"
    assert BRAND.support_email is None, "an unknown address must not be invented"
    assert BRAND.default_display_name() == f"{BRAND.name} 同学"

    module_text = (APP / "brand.py").read_text(encoding="utf-8")
    # The module defines the previous name as a value; it must not also *use* it as a brand.
    for variant in previous_name_variants():
        assert variant not in BRAND.name and variant not in BRAND.name_zh
    assert f'PREVIOUS_NAME: Final = "{PREVIOUS_NAME}"' in module_text


def test_the_visible_surfaces_read_the_brand_source() -> None:
    for relative, what in VISIBLE_SURFACES:
        text = (SERVICE / relative).read_text(encoding="utf-8")
        assert "from app.brand import BRAND" in text, (
            f"{relative} ({what}) does not import the brand"
        )
        assert "BRAND" in text.split("from app.brand import BRAND", 1)[1], relative


def _string_literals(path: pathlib.Path) -> list[tuple[int, str]]:
    """Every string literal in a module that is not a docstring.

    Docstrings are developer prose and comments never reach the parser, so neither can make this
    check fire; a literal that *would* be shown to a user or sent to a model always can.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstrings.add(id(body[0].value))

    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docstrings:
                found.append((node.lineno, node.value))
        elif isinstance(node, ast.JoinedStr):  # f-strings: their fixed parts are literals too
            for part in node.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    found.append((getattr(part, "lineno", node.lineno), part.value))
    return found


def test_no_visible_surface_still_prints_the_previous_name() -> None:
    """A literal may keep the old spelling only for a recorded contract or machine value."""
    offenders: list[str] = []
    for relative, what in VISIBLE_SURFACES:
        for number, literal in _string_literals(SERVICE / relative):
            if not re.search(
                rf"{PREVIOUS_NAME}|{PREVIOUS_NAME.upper()}|{PREVIOUS_NAME.lower()}", literal
            ):
                continue
            if any(allowed in literal for allowed in ALLOWED_ON_A_LINE):
                continue
            offenders.append(f"{relative}:{number} ({what}): {literal[:90]!r}")
    assert offenders == [], "visible literals still name the old brand:\n" + "\n".join(offenders)


def test_the_guard_can_actually_see_a_visible_literal() -> None:
    """A negative control: an extractor that found nothing would make the check pass silently."""
    literals = _string_literals(APP / "cm_update" / "db.py")
    assert any("database" in value.lower() for _line, value in literals), (
        "extractor found no literals"
    )
    # And it does not treat a docstring as a literal.
    docstring_only = APP / "brand.py"
    assert all(
        "single brand and URL source" not in value
        for _line, value in _string_literals(docstring_only)
    )


def test_the_persona_a_student_sees_is_built_from_the_brand_source() -> None:
    from app.rag.prompt import QA_INSTRUCTIONS

    assert QA_INSTRUCTIONS.startswith(f"You are {BRAND.name}, ")
    assert f"You are {PREVIOUS_NAME}," not in QA_INSTRUCTIONS

    # The Chinese teacher instruction, read from the module the model is actually given it by.
    provider_text = (APP / "cm_update" / "provider.py").read_text(encoding="utf-8")
    assert "你是 {BRAND.name} 教师" in provider_text
    assert f"你是 {PREVIOUS_NAME} 教师" not in provider_text


def test_the_api_titles_are_built_from_the_brand_source(tmp_path: pathlib.Path) -> None:
    """Built from the real factory, into a temporary database.

    The first version pointed the app at a literal `unused.sqlite3` and left a database file behind
    in the service directory; a test that writes into the repository is litter, not coverage.
    """
    from app.config import Settings
    from app.main import create_app  # noqa: PLC0415

    settings = Settings(
        database_path=tmp_path / "brand.sqlite3",
        upload_dir=tmp_path / "uploads",
        app_env="test",
        rag_provider_mode="deterministic",
        auth_test_user_id="brand-check",
        v3_enabled=True,
        ui_web_dir=tmp_path / "no-web-build",
    )
    application = create_app(settings=settings)
    assert application.title == f"{BRAND.name} RAG API"
    assert PREVIOUS_NAME not in application.title
    assert (tmp_path / "brand.sqlite3").is_file(), "the factory really initialised its database"


def test_the_compatibility_identifiers_are_still_present() -> None:
    """The pack's class B: these must survive the rename, so their absence is a failure.

    This is the static half only. Whether renaming one at a *use site* breaks something is a
    runtime question, and the UI-extension suites answer it: with `cmui_users` renamed in
    `auth.py` they fail with 6 failures and 16 errors
    (`work/current-change/check-cmui-rename-detection.py`).
    """
    haystack = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in (
            list(APP.rglob("*.py"))
            + [SERVICE.parent.parent / "apps" / "web" / "src" / "CourseMateUi.tsx"]
        )
        if path.is_file()
    )
    missing = [name for name in COMPATIBILITY_IDENTIFIERS if name not in haystack]
    assert missing == [], f"compatibility identifiers disappeared: {missing}"

    # The internal token header is a service-to-service contract, in both spellings in use.
    assert "X-CourseMate-Internal-Token" in haystack
    assert "x_coursemate_internal_token" in haystack


def test_no_unrecorded_identifier_derives_from_the_previous_name() -> None:
    """What a static check *can* enforce: no old-name identifier nobody recorded.

    That is how a careless rename (or a freshly invented one) slips in: it looks like a
    compatibility name, so nobody re-examines it. Recording one is a one-line, reasoned decision in
    `app/brand.py`; leaving it unrecorded is not.
    """
    pattern = re.compile(rf"{PREVIOUS_NAME}[A-Za-z][A-Za-z_]*|{PREVIOUS_NAME.lower()}_[a-z_]+")
    recorded = COMPATIBILITY_IDENTIFIERS
    unrecorded: dict[str, str] = {}
    for path in APP.rglob("*.py"):
        if path.name == "brand.py":
            continue
        for token in pattern.findall(path.read_text(encoding="utf-8", errors="replace")):
            if any(
                token == name or token.startswith(name) or name.startswith(token)
                for name in recorded
            ):
                continue
            unrecorded.setdefault(token, path.relative_to(SERVICE).as_posix())
    assert unrecorded == {}, (
        "old-name identifiers exist that are not recorded as compatibility contracts: "
        f"{unrecorded}. Record each in app/brand.py with its reason, or rename it."
    )


def test_the_brand_module_is_the_only_place_that_defines_the_name() -> None:
    """A second definition would drift; the front end has its own by design."""
    definitions = [
        path.relative_to(SERVICE).as_posix()
        for path in APP.rglob("*.py")
        if re.search(
            rf"^\s*{PREVIOUS_NAME}_?(NAME|BRAND)\s*=", path.read_text(encoding="utf-8"), re.M
        )
    ]
    assert definitions == []


@pytest.mark.parametrize("value", ["CourseJesus", "耶课稣"])
def test_the_two_names_are_the_ones_the_brief_requires(value: str) -> None:
    assert value in (BRAND.name, BRAND.name_zh)
