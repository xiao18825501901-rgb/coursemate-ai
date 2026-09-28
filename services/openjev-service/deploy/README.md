# Private OpenJev runtime

This unit is intentionally loopback-only. It runs one CPU q4 model instance,
uses a bounded queue, and has no public nginx route. The application must use
`http://127.0.0.1:28765` plus the root-owned bearer secret.

The release directory and frozen model snapshot are immutable inputs. Only
`/srv/coursemate/openjev/cache` is writable. `MemoryHigh` and `MemoryMax` protect
the existing learner-facing services on the 2C4G host; a limit breach fails the
local judge closed and does not enable a TypeSafe fallback.

Before enabling any hard gate, preserve the service benchmark and a scoped
qualification record for the exact model revision, dtype, case, language,
domain and input-transform version. Health or readiness alone is insufficient.
