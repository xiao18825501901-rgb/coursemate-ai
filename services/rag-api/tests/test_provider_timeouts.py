"""One explicit HTTP policy for every paid model client.

Measured on the installed SDK: the defaults are max_retries=2 and
Timeout(connect=5.0, read=600, write=600, pool=600).  Three clients in this
service were built with neither argument, so a single learner question could
become three billable calls with no record of the first two, and a stalled read
could hang for ten minutes while a connection had only five seconds to open.
These tests pin the policy and the fact that nothing bypasses it.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

import httpx
import pytest

from app.provider_client import (
    DEFAULT_CONNECT_SECONDS,
    DEFAULT_POOL_SECONDS,
    DEFAULT_READ_SECONDS,
    DEFAULT_WRITE_SECONDS,
    ProviderTimeouts,
    build_openai_client,
    timeouts_for,
)

APP_ROOT = Path(__file__).resolve().parents[1] / "app"


def test_the_policy_names_every_phase_and_every_value_is_finite() -> None:
    policy = ProviderTimeouts()
    receipt = policy.as_receipt()
    assert receipt == {
        "connectSeconds": DEFAULT_CONNECT_SECONDS,
        "readSeconds": DEFAULT_READ_SECONDS,
        "writeSeconds": DEFAULT_WRITE_SECONDS,
        "poolSeconds": DEFAULT_POOL_SECONDS,
        "operationDeadlineSeconds": (
            DEFAULT_CONNECT_SECONDS + DEFAULT_READ_SECONDS + DEFAULT_WRITE_SECONDS
        ),
    }
    for value in receipt.values():
        assert math.isfinite(value) and value > 0


def test_a_caller_can_widen_the_read_budget_but_not_remove_it() -> None:
    widened = timeouts_for(read_seconds=600)
    assert widened.read_seconds == 600
    assert widened.connect_seconds == DEFAULT_CONNECT_SECONDS
    with pytest.raises(ValueError):
        ProviderTimeouts(read_seconds=float("inf"))
    with pytest.raises(ValueError):
        ProviderTimeouts(read_seconds=0)
    with pytest.raises(ValueError):
        ProviderTimeouts(connect_seconds=-1)


def test_the_built_client_carries_the_policy_and_zero_retries() -> None:
    client = build_openai_client(api_key="sk-test", base_url="https://api.deepseek.com")
    assert client.max_retries == 0
    timeout = client.timeout
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.connect == DEFAULT_CONNECT_SECONDS
    assert timeout.read == DEFAULT_READ_SECONDS
    assert timeout.write == DEFAULT_WRITE_SECONDS
    assert timeout.pool == DEFAULT_POOL_SECONDS
    # The SDK defaults this replaced, stated so a regression is obvious.
    assert timeout.connect != 5.0
    assert timeout.read != 600


def test_an_automatic_retry_cannot_be_asked_for_here() -> None:
    with pytest.raises(ValueError):
        build_openai_client(api_key="sk-test", max_retries=2)


def test_no_module_constructs_a_paid_client_outside_the_policy() -> None:
    """A source-level guard, because inheriting the defaults is silent.

    Importing the symbol for a type annotation is fine; calling it is not.
    """
    offenders: list[str] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        if path.name == "provider_client.py":
            continue
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"(?<![\w.])OpenAI\s*\(", text):
            line = text.count("\n", 0, match.start()) + 1
            offenders.append(f"{path.relative_to(APP_ROOT)}:{line}")
    assert offenders == [], (
        "every paid client must be built by app.provider_client.build_openai_client: "
        + ", ".join(offenders)
    )

def test_a_json_object_wrapped_in_prose_is_extracted() -> None:
    """A complete response is not thrown away over its packaging.

    One measured run lost a paid call to "<root>: json_invalid" -- a complete body
    that was valid JSON inside a fence or a sentence.  The extracted text is
    validated against the same schema, so this changes what is parsed, never what
    is accepted.
    """
    from app.learning.provider import extract_json_object

    assert extract_json_object('{"a": 1}') is None  # bare: the content is the issue
    assert extract_json_object("no object here") is None
    assert extract_json_object('before {"a": 1} after') == '{"a": 1}'
    assert extract_json_object('```json\n{"a": 2}\n```') == '{"a": 2}'
    # Two objects are ambiguous, so nothing is extracted and the refusal stands.
    assert extract_json_object('{"a": 1} and {"b": 2}') is None
    # Unbalanced or unparseable candidates are left alone too.
    assert extract_json_object('prefix {"a": 1') is None
    assert extract_json_object("prefix {not json} suffix") is None
