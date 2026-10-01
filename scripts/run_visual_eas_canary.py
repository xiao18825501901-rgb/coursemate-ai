"""Compatibility entrypoint for the process-environment EAS canary.

The legacy document-carrier implementation was intentionally retired. This
entrypoint never reads a document or supplies endpoint/token defaults; it uses
the same one-POST, no-retry implementation as ``run_visual_eas_env_canary``.
"""

from __future__ import annotations

from run_visual_eas_env_canary import main

if __name__ == "__main__":
    raise SystemExit(main())
