"""Install a scoped hybrid qualification into a database, from its evaluation record.

This is the management entry point the deployment plan asks for.  It exists because
the alternative -- writing the row with SQL, or letting a migration seed it active --
is indistinguishable from claiming a qualification nobody measured.

What it refuses:

* an artifact whose decision is not SCOPED_QUALITY_ACCEPTED;
* an artifact with no dataset digest, no method identity, or no expiry;
* an artifact measured under a method this code no longer implements -- the
  prompt, schema and combination versions are part of the identity, so an
  artifact that predates a change to any of them describes a procedure nobody
  can reproduce, and installing it would record a qualification for that
  vanished procedure;
* a target that does not survive the copy guard for the purpose it names;
* a production write that does not name a declared production database.

Installation is a database write and says so: `--install` is required, and without
it the command validates the artifact and prints exactly what it would record.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402
from app.db import Database  # noqa: E402
from app.db_target import DatabaseTargetError, resolve_database_target  # noqa: E402
from app.learning.hybrid_quality import HybridQualificationStore  # noqa: E402


def _current_method_identity(observed: dict) -> str:
    """The method identity this code implements, rebuilt from the artifact's own facts.

    The provider, protocol and model alias come from the artifact because they are
    runtime facts of the run that was measured; every prompt, schema and the
    combination rule come from the code, because those are what the artifact
    cannot tell us about.
    """
    from app.learning.deepseek_reviewer import (
        ADVERSARIAL_AUDIT_PROMPT_VERSION,
        EVIDENCE_AUDIT_PROMPT_VERSION,
        SPECIFICATION_AUDIT_PROMPT_VERSION,
        SPECIFICATION_SCHEMA_VERSION,
        STRONG_REVIEW_SCHEMA_VERSION,
    )
    from app.learning.hybrid_review import method_identity

    return method_identity(
        model_alias=str(observed.get("model_alias") or ""),
        provider=str(observed.get("provider") or ""),
        protocol=str(observed.get("protocol") or ""),
        evidence_prompt_version=EVIDENCE_AUDIT_PROMPT_VERSION,
        adversarial_prompt_version=ADVERSARIAL_AUDIT_PROMPT_VERSION,
        specification_prompt_version=SPECIFICATION_AUDIT_PROMPT_VERSION,
        schema_version=STRONG_REVIEW_SCHEMA_VERSION,
        specification_schema_version=SPECIFICATION_SCHEMA_VERSION,
    )


def _load_artifact(path: str) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("the evaluation artifact is not an object")
    decision = payload.get("decision")
    if not isinstance(decision, dict):
        raise ValueError("the evaluation artifact carries no decision")
    status = decision.get("status")
    if status != "SCOPED_QUALITY_ACCEPTED":
        raise ValueError(
            f"the artifact decision is {status!r}; only an accepted evaluation may "
            "be installed"
        )
    for field in ("policy_revision", "method_identity", "reviewer_label", "summary"):
        if not decision.get(field):
            raise ValueError(f"the accepted decision carries no {field}")
    for field in ("expires_at", "dataset"):
        if not payload.get(field):
            raise ValueError(f"the artifact carries no {field}")
    digest = (payload.get("dataset") or {}).get("digest")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError("the artifact carries no dataset digest")
    cases = decision.get("cases")
    if not cases:
        raise ValueError("the accepted decision names no cases")
    observed = decision.get("observed_model_facts")
    if not isinstance(observed, dict):
        raise ValueError("the accepted decision carries no observed model facts")
    current = _current_method_identity(observed)
    if decision.get("method_identity") != current:
        raise ValueError(
            "the artifact was measured under a different method identity than "
            f"this code implements (artifact {decision.get('method_identity')}, "
            f"code {current}); re-measure before installing"
        )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--allowed-root", required=True)
    parser.add_argument("--production-database", action="append", default=[])
    parser.add_argument("--expected-schema", type=int, default=None)
    parser.add_argument("--qualification-id", required=True)
    parser.add_argument(
        "--production",
        action="store_true",
        help=("install into a declared production database; without it the target "
              "must be a copy inside the allowed root"),
    )
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()

    try:
        artifact = _load_artifact(args.artifact)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "REFUSED", "reason": str(error)}, ensure_ascii=False))
        return 2

    try:
        target = resolve_database_target(
            purpose="PRODUCTION_WRITE" if args.production else "QUALIFICATION_RUN",
            explicit_path=args.database,
            allowed_root=args.allowed_root,
            production_paths=tuple(args.production_database),
            expected_schema=args.expected_schema,
        )
    except DatabaseTargetError as refusal:
        print(json.dumps(refusal.as_dict(), ensure_ascii=False))
        return 6

    decision = artifact["decision"]
    payload = {
        "qualification_id": args.qualification_id,
        "policy_revision": decision["policy_revision"],
        "method_identity": decision["method_identity"],
        "status": decision["status"],
        "reviewer_label": decision["reviewer_label"],
        "languages": decision["languages"],
        "domains": decision["domains"],
        "cases": decision["cases"],
        "roles": ["evidence_audit", "adversarial_audit"],
        "sample_counts": {
            "positive_rows": decision["summary"]["positive_rows"],
            "negative_rows": decision["summary"]["negative_rows"],
            "independent_negative_families": decision["summary"][
                "independent_negative_families"
            ],
        },
        "evidence_manifest_digest": artifact["dataset"]["digest"],
        "expires_at": artifact["expires_at"],
        "target": target.as_receipt(),
    }
    if not args.install:
        print(json.dumps({**payload, "status": payload["status"], "installed": False},
                         ensure_ascii=False, indent=2))
        return 0

    settings = Settings()
    database = Database(
        settings.model_copy(
            update={
                "database_path": target.path,
                "upload_dir": target.path.parent / "uploads",
            }
        )
    )
    store = HybridQualificationStore(database)
    record = store.record(
        qualification_id=args.qualification_id,
        policy_revision=decision["policy_revision"],
        method_identity=decision["method_identity"],
        status=decision["status"],
        reviewer_label=decision["reviewer_label"],
        languages=decision["languages"],
        domains=decision["domains"],
        cases=decision["cases"],
        roles=["evidence_audit", "adversarial_audit"],
        sample_counts=payload["sample_counts"],
        metrics=decision["summary"],
        evidence_manifest_digest=artifact["dataset"]["digest"],
        observed_model_facts=decision.get("observed_model_facts") or {},
        expires_at=artifact["expires_at"],
    )
    print(
        json.dumps(
            {
                "installed": True,
                "qualification_id": record.id,
                "status": record.status,
                "method_identity": record.method_identity,
                "languages": record.languages,
                "domains": record.domains,
                "cases": record.cases,
                "expires_at": record.expires_at,
                "active": record.active,
                "target_identity": target.identity,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
