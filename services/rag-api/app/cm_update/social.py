"""Campus-course verification, course snapshot sharing, and template
classification helpers for the cm_update UI app.

These are pure helpers: routes live in app.py. All secrets stay server-side;
verification codes are stored as HMAC(server_secret, code) digests, never as
plaintext or bare hashes. Share snapshots are frozen at send time; join copies
them into the recipient's own scope with provenance preserved.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets as _secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .db import Database, now, uid
from . import templates


# ------------------------------------------------------------------- verification

def _secret(settings) -> str:
    value = getattr(settings, "verification_secret", "") or ""
    if value:
        return value
    if getattr(settings, "environment", "development") != "production":
        # Stable dev default so local tests survive restarts; production
        # REQUIRES CMUI_VERIFICATION_SECRET (enforced by Settings.validate).
        return "coursemate-dev-verification-secret"
    raise RuntimeError("CMUI_VERIFICATION_SECRET is required in production")


def code_secret_hash(settings, code: str) -> str:
    return hmac.new(_secret(settings).encode(), code.encode(), hashlib.sha256).hexdigest()


def generate_codes(db: Database, settings, count: int, issued_by: str) -> list[str]:
    """Issue `count` fresh 7-digit codes. Collisions retry against the UNIQUE
    code column. Returns the plaintext codes exactly once (caller returns them
    to the issuing admin; they are never logged by this module)."""
    issued: list[str] = []
    attempts = 0
    while len(issued) < count and attempts < count * 20:
        attempts += 1
        code = f"{_secrets.randbelow(10_000_000):07d}"
        digest = code_secret_hash(settings, code)
        try:
            with db.connect(True) as c:
                c.execute(
                    "INSERT INTO cmui_verification_codes(code,secret_hash,status,"
                    "issued_by,issued_at) VALUES(?,?,'issued',?,?)",
                    (code, digest, issued_by, now()),
                )
        except sqlite3.IntegrityError:
            continue
        issued.append(code)
    return issued


def verification_status(db: Database, owner: str) -> dict[str, Any]:
    row = db.one("SELECT * FROM cmui_verification WHERE owner=?", (owner,))
    if row is None:
        return {"verified": False, "method": None, "verified_at": None}
    return {"verified": bool(row["verified"]), "method": row["method"],
            "verified_at": row["verified_at"]}


def set_verified(db: Database, owner: str, method: str, notes: str = "") -> None:
    db.execute(
        "INSERT INTO cmui_verification(owner,verified,method,verified_at,boundary_notes,updated_at) "
        "VALUES(?,1,?,?,?,?) ON CONFLICT(owner) DO UPDATE SET verified=1,"
        "method=excluded.method,verified_at=excluded.verified_at,"
        "boundary_notes=excluded.boundary_notes,updated_at=excluded.updated_at",
        (owner, method, now(), notes, now()),
    )


def redeem_code(db: Database, settings, owner: str, code: str, request_id: str) -> dict[str, Any]:
    """Redeem a 7-digit code. One code binds to at most one account; the same
    account re-redeeming its own code is idempotent. Transaction + row lock
    guard concurrent redemptions; rate limiting happens at the route level."""
    digest = code_secret_hash(settings, code)
    with db.connect(True) as c:
        row = c.execute("SELECT * FROM cmui_verification_codes WHERE code=?", (code,)).fetchone()
        if row is None:
            _attempt(c, owner, code, request_id, 0)
            return {"ok": False, "reason": "INVALID_CODE"}
        if row["status"] == "disabled":
            _attempt(c, owner, code, request_id, 0)
            return {"ok": False, "reason": "CODE_DISABLED"}
        if row["status"] == "redeemed":
            if row["owner"] == owner:
                _attempt(c, owner, code, request_id, 1)
                return {"ok": True, "reason": "ALREADY_REDEEMED", "verified": True}
            _attempt(c, owner, code, request_id, 0)
            return {"ok": False, "reason": "CODE_ALREADY_USED"}
        updated = c.execute(
            "UPDATE cmui_verification_codes SET owner=?,status='redeemed',redeemed_at=? "
            "WHERE code=? AND status='issued'",
            (owner, now(), code),
        ).rowcount
        if updated != 1:
            _attempt(c, owner, code, request_id, 0)
            return {"ok": False, "reason": "CODE_ALREADY_USED"}
        c.execute(
            "INSERT INTO cmui_verification(owner,verified,method,verified_at,boundary_notes,updated_at) "
            "VALUES(?,1,'code',?,?,?) ON CONFLICT(owner) DO UPDATE SET verified=1,"
            "method='code',verified_at=excluded.verified_at,updated_at=excluded.updated_at",
            (owner, now(), "redeemed " + code, now()),
        )
        _audit(c, code, owner, "redeemed")
        _attempt(c, owner, code, request_id, 1)
    return {"ok": True, "reason": "REDEEMED", "verified": True}


def _attempt(c, owner: str, code: str, request_id: str, success: int) -> None:
    c.execute(
        "INSERT INTO cmui_redemption_attempts(id,code,owner,success,created_at) VALUES(?,?,?,?,?)",
        (uid("attempt_"), code, owner, success, now()),
    )


def _audit(c, code: str, actor: str, action: str) -> None:
    row = c.execute("SELECT audit FROM cmui_verification_codes WHERE code=?", (code,)).fetchone()
    entries = json.loads(row["audit"] or "[]") if row else []
    entries.append({"at": now(), "actor": actor, "action": action})
    c.execute("UPDATE cmui_verification_codes SET audit=? WHERE code=?",
              (json.dumps(entries, ensure_ascii=False), code))


def grandfather_existing_users(db: Database, candidates: list[str]) -> None:
    """One-time boundary migration: verify every user that existed BEFORE this
    feature was enabled, recorded via a persisted meta key so later runs never
    certify new users. `candidates` is the protected snapshot of pre-existing
    user ids (built by the caller from trusted sources)."""
    if db.one("SELECT value FROM cmui_meta WHERE key='verification_grandfather_boundary'"):
        return
    boundary_at = now()
    for owner in candidates:
        if db.one("SELECT id FROM cmui_users WHERE id=?", (owner,)):
            set_verified(db, owner, "grandfathered", f"pre-enablement snapshot at {boundary_at}")
    db.execute(
        "INSERT INTO cmui_meta(key,value) VALUES('verification_grandfather_boundary',?) "
        "ON CONFLICT(key) DO NOTHING",
        (json.dumps({"at": boundary_at, "users": candidates}, ensure_ascii=False),),
    )


# ------------------------------------------------------------------- classification

CLASSIFY_DECISION_KEYS = {"template_id", "decision", "degree_level", "confidence",
                          "alternatives", "reason", "evidence_refs", "materials_revision"}


def materials_revision(files: list[dict[str, Any]]) -> str:
    key = json.dumps(sorted((f.get("id"), f.get("sha256") or "") for f in files),
                     ensure_ascii=False)
    return hashlib.sha256(key.encode()).hexdigest()


def validate_classification(db: Database, result: dict[str, Any]) -> dict[str, Any]:
    """Backend-side candidate validation before a classification is adopted."""
    template_id = str(result.get("template_id") or "OTHER")
    decision = str(result.get("decision") or "other")
    confidence = result.get("confidence")
    if template_id not in templates.registry() and template_id != "OTHER":
        template_id = "OTHER"
        decision = "other"
    if decision != "classified" or template_id == "OTHER":
        return {"template_id": "OTHER", "decision": "other", "degree_level": None,
                "confidence": None, "alternatives": [],
                "reason": result.get("reason") or "insufficient_evidence",
                "evidence_refs": result.get("evidence_refs") or [],
                "materials_revision": result.get("materials_revision")}
    level = result.get("degree_level")
    if level not in {"undergraduate", "graduate"}:
        level = None
    if not isinstance(confidence, (int, float)) or float(confidence) < 0.6:
        # Uncalibrated model confidence below the adoption threshold falls back
        # to OTHER rather than randomly picking a professional template.
        return {"template_id": "OTHER", "decision": "other", "degree_level": None,
                "confidence": float(confidence) if isinstance(confidence, (int, float)) else None,
                "alternatives": result.get("alternatives") or [],
                "reason": result.get("reason") or "confidence_below_threshold",
                "evidence_refs": result.get("evidence_refs") or [],
                "materials_revision": result.get("materials_revision")}
    return {"template_id": template_id, "decision": "classified", "degree_level": level,
            "confidence": float(confidence), "alternatives": result.get("alternatives") or [],
            "reason": result.get("reason") or "", "evidence_refs": result.get("evidence_refs") or [],
            "materials_revision": result.get("materials_revision")}


# ------------------------------------------------------------------- shares

def build_share_manifest(db: Database, settings, sender: str, course_row: dict[str, Any],
                         files: list[dict[str, Any]], history_scope: str,
                         pair_rows: list[dict[str, Any]]) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "files": [{"id": f["id"], "name": f["name"], "size": f["size"],
                   "mime": f["mime"], "sha256": f["sha256"]} for f in files],
        "history_scope": history_scope,
        "pairs": pair_rows,
        "course": {"name": course_row.get("name"), "code": course_row.get("code"),
                   "description": course_row.get("description", "")},
        "requires_student_verification": bool(
            course_row.get("requires_student_verification")
            or course_row.get("display_type") == "campus"
        ),
    }
    return manifest


def snapshot_pair_payload(db: Database, sender: str, course: str,
                          pair_ids: list[str]) -> list[dict[str, Any]]:
    """Frozen message/exercise payload for the selected pairs (or all pairs of
    the course when history_scope='all'). Never includes runs, plan text,
    usage or third-party content."""
    pairs: list[dict[str, Any]] = []
    if pair_ids:
        rows = []
        for pid in pair_ids:
            row = db.one(
                "SELECT * FROM cmui_pairs WHERE id=? AND owner=? AND course=?", (pid, sender, course))
            if row:
                rows.append(row)
    else:
        rows = db.all(
            "SELECT * FROM cmui_pairs WHERE owner=? AND course=? ORDER BY created_at",
            (sender, course))
    for pair in rows:
        payload = {"id": pair["id"], "title": pair["title"], "bound_node": pair["bound_node"],
                  "teach": [], "problem": []}
        for key, lane in (("teach", "teach"), ("problem", "problem")):
            conv_id = pair.get(f"{lane}_conversation")
            if not conv_id:
                continue
            messages = db.all(
                "SELECT id, role, text, citations, created_at FROM cmui_messages "
                "WHERE conversation=? ORDER BY created_at,rowid", (conv_id,))
            payload[key] = [dict(m) for m in messages]
        pairs.append(payload)
    return pairs


def copy_share_files(db: Database, settings, share_id: str,
                     files: list[dict[str, Any]]) -> int:
    """Copy the sender's file bytes into the share's own immutable storage so a
    later upload by the sender cannot change the snapshot."""
    dest_dir = Path(settings.data_dir) / "shares" / share_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for f in files:
        row = db.one("SELECT * FROM cmui_files WHERE id=? AND course=?",
                     (f["id"], f.get("course") or f.get("course_id") or ""))
        if row is None:
            row = db.one("SELECT * FROM cmui_files WHERE id=?", (f["id"],))
        if row is None:
            continue
        source = Path(settings.data_dir) / "uploads" / row["storage_key"]
        if not source.is_file():
            continue
        target = dest_dir / (row["id"] + Path(row["name"]).suffix.lower())
        target.write_bytes(source.read_bytes())
        db.execute(
            "INSERT OR IGNORE INTO cmui_share_files(share,file_id,name,size,mime,sha256,"
            "archived_storage_key) VALUES(?,?,?,?,?,?,?)",
            (share_id, row["id"], row["name"], row["size"], row["mime"],
             row["sha256"], f"shares/{share_id}/{target.name}"),
        )
        copied += 1
    return copied


def record_join(db: Database, share: dict[str, Any], recipient: str, joined_course_id: str) -> dict[str, Any]:
    """Idempotent recipient-side join bookkeeping. Course creation itself is
    caller-provided (standalone: cmui_courses; integrated: a real V3 course via
    the domain adapter)."""
    existing = db.one("SELECT * FROM cmui_share_recipients WHERE share=? AND recipient=?",
                      (share["id"], recipient))
    if existing and existing["joined_course_id"]:
        return {"joined_course_id": existing["joined_course_id"], "reused": True}
    with db.connect(True) as c:
        c.execute(
            "INSERT INTO cmui_share_recipients(share,recipient,status,joined_course_id,joined_at) "
            "VALUES(?,?,'joined',?,?) ON CONFLICT(share,recipient) DO UPDATE SET "
            "status='joined',joined_course_id=excluded.joined_course_id,joined_at=excluded.joined_at",
            (share["id"], recipient, joined_course_id, now()),
        )
    return {"joined_course_id": joined_course_id, "reused": False}


def import_share_history(db: Database, share: dict[str, Any], recipient: str, course_id: str) -> None:
    """Remap the frozen pair payload into recipient-owned pairs. Provenance is
    preserved per message; runs, usage and plan text are never copied. Learning
    state and grades are intentionally NOT imported."""
    manifest = json.loads(share["manifest_json"])
    for pair in manifest.get("pairs") or []:
        pair_id = uid("pair_")
        with db.connect(True) as c:
            c.execute(
                "INSERT INTO cmui_pairs(id,owner,course,teach_conversation,problem_conversation,"
                "title,bound_node,created_at,updated_at) VALUES(?,?,?,NULL,NULL,?,NULL,?,?)",
                (pair_id, recipient, course_id, (pair.get("title") or "新对话"), now(), now()),
            )
        for key, lane in (("teach", "teach"), ("problem", "problem")):
            for message in pair.get(key) or []:
                conv_id = _lane_conversation(db, pair_id, recipient, course_id, lane, pair)
                mid = uid("message_")
                db.execute(
                    "INSERT INTO cmui_messages(id,conversation,role,text,citations,run,created_at,"
                    "provenance,exercise) VALUES(?,?,?,?,?,?,?,?,NULL)",
                    (mid, conv_id, message["role"], message["text"],
                     message.get("citations") or "[]", None,
                     message.get("created_at") or now(), f"share:{share['id']}"),
                )


def join_share(db: Database, settings, share: dict[str, Any], recipient: str) -> dict[str, Any]:
    """Standalone-mode join: create the recipient's cmui course, copy the
    snapshot files into their scope, remap history, keep provenance."""
    result = record_join(db, share, recipient, "")
    if result.get("reused"):
        return result
    manifest = json.loads(share["manifest_json"])
    course_meta = manifest.get("course") or {}
    cid = uid("course_")
    with db.connect(True) as c:
        c.execute(
            "INSERT INTO cmui_courses(id,owner,code,name,description,color,visibility,official,"
            "requirements,display_type,requires_student_verification,created_at) "
            "VALUES(?,?,?,?,?,?,'private',0,'',?,?,?)",
            (cid, recipient, "共享课程", course_meta.get("name") or "共享课程",
             course_meta.get("description") or "", "#38585b",
             "shared", 1 if share["requires_student_verification"] else 0, now()),
        )
    record_join(db, share, recipient, cid)
    # files: copy bytes from the share's frozen storage into the recipient's uploads
    for f in db.all("SELECT * FROM cmui_share_files WHERE share=?", (share["id"],)):
        src = Path(settings.data_dir) / "shares" / share["id"] / (f["file_id"] + Path(f["name"]).suffix.lower())
        storage = uid("file_") + Path(f["name"]).suffix.lower()
        target = Path(settings.data_dir) / "uploads" / storage
        try:
            if src.is_file():
                target.write_bytes(src.read_bytes())
                db.execute(
                    "INSERT OR IGNORE INTO cmui_files(id,course,owner,name,folder,size,mime,"
                    "storage_key,sha256,scope,status,error,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (f["file_id"], cid, recipient, f["name"], "", f["size"], f["mime"],
                     storage, f["sha256"], "private", "indexed", None, now()),
                )
        except OSError:
            continue
    import_share_history(db, share, recipient, cid)
    return {"joined_course_id": cid, "reused": False}


def _lane_conversation(db: Database, pair_id: str, owner: str, course: str, lane: str,
                       pair: dict[str, Any]) -> str:
    column = f"{lane}_conversation"
    row = db.one("SELECT * FROM cmui_pairs WHERE id=?", (pair_id,))
    conv_id = row[column] if row else None
    if conv_id:
        return conv_id
    conv_id = uid("conv_")
    db.execute(
        "INSERT INTO cmui_conversations(id,owner,course,lane,title,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (conv_id, owner, course, lane, pair.get("title") or "新对话", now(), now()),
    )
    db.execute(f"UPDATE cmui_pairs SET {column}=? WHERE id=?", (conv_id, pair_id))
    return conv_id
