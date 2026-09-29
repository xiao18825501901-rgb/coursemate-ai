"""One explicit HTTP policy for every paid model client.

Measured on the installed SDK (openai 2.53.0, this runtime):

```
DEFAULT_MAX_RETRIES: 2
DEFAULT_TIMEOUT: Timeout(connect=5.0, read=600, write=600, pool=600)
```

Three clients in this service were constructed with neither argument, so they
inherited exactly that.  The consequences are not stylistic:

* **Two silent automatic retries.**  A single learner question could become three
  billable provider calls with no record anywhere that the first two were
  retried, which is the opposite of "no silent automatic retry" and it corrupts
  any count of what was actually sent.
* **A 5-second connect budget against a 600-second read budget.**  The plan warns
  about exactly this asymmetry: a short window is not an operation timeout, and a
  ten-minute read is not a deadline.  Both were unrecorded.

So the policy lives here, in one place, with every phase named and every value
finite.  Zero retries is the default, and callers pass their own read budget
because a 4000-token review and a short answer do not need the same one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

import httpx
from openai import OpenAI

# A handshake to a public API from this host.  The SDK default of 5 s is too tight
# for a cross-region link, and the measurement that suggests so is this host own
# throughput to its peers, not a guess.
DEFAULT_CONNECT_SECONDS: Final = 10.0
# Uploading a request body; bounded and generous.
DEFAULT_WRITE_SECONDS: Final = 30.0
# Waiting for a free connection from the pool.  Bounded so a saturated client
# fails loudly instead of queueing forever.
DEFAULT_POOL_SECONDS: Final = 30.0
# Reading a completion.  Callers that ask for thousands of output tokens pass
# their own, larger, value.
DEFAULT_READ_SECONDS: Final = 120.0


@dataclass(frozen=True)
class ProviderTimeouts:
    """Every phase budget, named, finite and recorded in one object."""

    connect_seconds: float = DEFAULT_CONNECT_SECONDS
    read_seconds: float = DEFAULT_READ_SECONDS
    write_seconds: float = DEFAULT_WRITE_SECONDS
    pool_seconds: float = DEFAULT_POOL_SECONDS

    def __post_init__(self) -> None:
        for name in ("connect_seconds", "read_seconds", "write_seconds", "pool_seconds"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(f"{name} must be a number")
            if not math.isfinite(value) or value <= 0:
                raise ValueError(
                    f"{name} must be finite and positive; an unbounded wait is not a timeout"
                )

    @property
    def operation_deadline_seconds(self) -> float:
        """A finite upper bound for one whole call, phase budgets included."""
        return self.connect_seconds + self.read_seconds + self.write_seconds

    def as_httpx(self) -> httpx.Timeout:
        return httpx.Timeout(
            self.read_seconds,
            connect=self.connect_seconds,
            read=self.read_seconds,
            write=self.write_seconds,
            pool=self.pool_seconds,
        )

    def as_receipt(self) -> dict[str, float]:
        return {
            "connectSeconds": self.connect_seconds,
            "readSeconds": self.read_seconds,
            "writeSeconds": self.write_seconds,
            "poolSeconds": self.pool_seconds,
            "operationDeadlineSeconds": self.operation_deadline_seconds,
        }


def timeouts_for(*, read_seconds: float | None = None, **overrides: float) -> ProviderTimeouts:
    """The policy for one caller, with its own read budget when it needs one."""
    if read_seconds is not None:
        overrides["read_seconds"] = float(read_seconds)
    return ProviderTimeouts(**overrides)


def build_openai_client(
    *,
    api_key: str,
    base_url: str | None = None,
    timeouts: ProviderTimeouts | None = None,
    max_retries: int = 0,
) -> OpenAI:
    """The only way this codebase constructs a paid model client.

    max_retries defaults to zero: a retry is a new billable call and must be an
    explicit, recorded decision rather than an SDK default.
    """
    if max_retries != 0:
        raise ValueError(
            "Automatic retries are not permitted here; a retry must be an explicit, "
            "recorded attempt rather than an SDK default."
        )
    policy = timeouts or ProviderTimeouts()
    if base_url:
        return OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=policy.as_httpx(),
            max_retries=0,
        )
    return OpenAI(api_key=api_key, timeout=policy.as_httpx(), max_retries=0)
