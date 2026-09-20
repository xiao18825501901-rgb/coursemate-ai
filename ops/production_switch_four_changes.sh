#!/usr/bin/env bash
# Apply the CourseMate four-change runtime release during one bounded maintenance
# window. This script intentionally has no secret values and must be run as root
# only after a separately verified, immutable full backup has been made.
set -Eeuo pipefail

: "${VERIFIED_BACKUP:?Set VERIFIED_BACKUP to the verified full-backup directory.}"

RAG_ENV="${RAG_ENV:-/etc/coursemate/rag.env}"
CURRENT_LINK="${CURRENT_LINK:-/srv/coursemate/current}"
OLD_RELEASE="${OLD_RELEASE:-/srv/coursemate/releases/46415bd}"
NEW_RELEASE="${NEW_RELEASE:-/srv/coursemate/releases/4ef5064}"
FALLBACK_RELEASE="${FALLBACK_RELEASE:-/srv/coursemate/releases/c484bb9-fallback}"
PYTHON_BIN="${PYTHON_BIN:-/srv/coursemate/runtime/rag/bin/python}"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
CONFIG_BACKUP_ROOT="${CONFIG_BACKUP_ROOT:-/etc/coursemate/backups/four-changes-${RUN_ID}}"
CONFIG_BACKUP="${CONFIG_BACKUP_ROOT}/rag.env.before-schema13"

if [[ "$(id -u)" != "0" ]]; then
  echo "Run this release switch as root." >&2
  exit 2
fi

require_dir() { [[ -d "$1" ]] || { echo "Required directory is missing: $1" >&2; exit 2; }; }
require_file() { [[ -f "$1" ]] || { echo "Required file is missing: $1" >&2; exit 2; }; }

require_dir "$VERIFIED_BACKUP"
require_file "$VERIFIED_BACKUP/manifest.json"
require_file "$VERIFIED_BACKUP/SHA256SUMS"
(cd "$VERIFIED_BACKUP" && sha256sum --check --status SHA256SUMS) || {
  echo "The required backup checksum verification failed." >&2
  exit 2
}
require_file "$RAG_ENV"
require_dir "$OLD_RELEASE"
require_dir "$NEW_RELEASE"
require_dir "$FALLBACK_RELEASE"
[[ "$(readlink -f "$CURRENT_LINK")" == "$OLD_RELEASE" ]] || {
  echo "Refusing to switch: current release is not the reviewed pre-migration release." >&2
  exit 2
}
[[ "$(grep -E '^SCHEMA_VERSION = ' "$NEW_RELEASE/services/rag-api/app/cm_update/db.py" | awk '{print $3}')" == "13" ]] || {
  echo "New runtime is not a Schema 13 runtime." >&2
  exit 2
}
[[ "$(grep -E '^SCHEMA_VERSION = ' "$FALLBACK_RELEASE/services/rag-api/app/cm_update/db.py" | awk '{print $3}')" == "13" ]] || {
  echo "Fallback runtime cannot read Schema 13." >&2
  exit 2
}

set_current() {
  local target="$1"
  local next="${CURRENT_LINK}.next-${RUN_ID}"
  [[ ! -e "$next" && ! -L "$next" ]] || { echo "Temporary current pointer already exists: $next" >&2; return 1; }
  ln -s "$target" "$next"
  mv -Tf "$next" "$CURRENT_LINK"
}

initial_rag=0
initial_agent=0
systemctl is-active --quiet coursemate-rag && initial_rag=1 || true
systemctl is-active --quiet coursemate-agent && initial_agent=1 || true
[[ "$initial_rag" == "1" && "$initial_agent" == "1" ]] || {
  echo "Both CourseMate services must be healthy before this bounded release window." >&2
  exit 2
}

migration_complete=0
switched=0
rollback() {
  local code="$1"
  trap - ERR
  set +e
  systemctl stop coursemate-agent coursemate-rag
  if [[ "$migration_complete" == "1" ]]; then
    # Once the database is Schema 13, never restart the Schema-11 release.
    set_current "$FALLBACK_RELEASE"
    systemctl start coursemate-rag
    systemctl start coursemate-agent
    echo "ROLLBACK=schema13-compatible-fallback" >&2
  else
    cp -p "$CONFIG_BACKUP" "$RAG_ENV"
    set_current "$OLD_RELEASE"
    systemctl start coursemate-rag
    systemctl start coursemate-agent
    echo "ROLLBACK=pre-migration-runtime-and-config" >&2
  fi
  exit "$code"
}
trap 'rollback "$?"' ERR

install -d -m 0700 "$CONFIG_BACKUP_ROOT"
[[ ! -e "$CONFIG_BACKUP" ]] || { echo "Configuration backup already exists: $CONFIG_BACKUP" >&2; exit 2; }
cp -p "$RAG_ENV" "$CONFIG_BACKUP"
chmod 0600 "$CONFIG_BACKUP"

# Only non-secret four-change policy values are updated. Existing variables,
# including provider credentials and legacy diagnostics, are preserved exactly.
RAG_ENV="$RAG_ENV" /usr/bin/python3 - <<'PY'
import os
from pathlib import Path

path = Path(os.environ["RAG_ENV"])
updates = {
    "CMUI_OPERATION_USD_BASELINE": "0.20",
    "CMUI_OPERATION_INPUT_USD_PER_MILLION": "2",
    "CMUI_OPERATION_OUTPUT_USD_PER_MILLION": "6",
    "CMUI_IMAGE_MAX_PIXELS": "2621440",
    "CMUI_CAMPUS_QUALIFICATION_POLICY": "registered_active",
}
seen: set[str] = set()
lines: list[str] = []
for line in path.read_text(encoding="utf-8").splitlines():
    key, separator, _ = line.partition("=")
    if separator and key in updates:
        if key not in seen:
            lines.append(f"{key}={updates[key]}")
            seen.add(key)
        continue
    lines.append(line)
for key, value in updates.items():
    if key not in seen:
        lines.append(f"{key}={value}")
temporary = path.with_name(path.name + ".four-changes-next")
if temporary.exists():
    raise RuntimeError(f"Refusing to overwrite temporary environment file: {temporary}")
stat = path.stat()
temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
os.chmod(temporary, stat.st_mode)
os.chown(temporary, stat.st_uid, stat.st_gid)
os.replace(temporary, path)
print("CONFIGURATION=updated non-secret policy keys=5")
PY

systemctl stop coursemate-agent coursemate-rag

set -a
# shellcheck disable=SC1090
. "$RAG_ENV"
set +a
export PYTHONPATH="$NEW_RELEASE/services/rag-api"
cd "$NEW_RELEASE/services/rag-api"
runuser -u coursemate --preserve-environment -- "$PYTHON_BIN" - <<'PY'
from pathlib import Path
import os
from app.main import create_app
from app.cm_update.db import Database

app = create_app()
db = Database(Path(os.environ["CMUI_DATA_DIR"]) / "ui.sqlite3")
with db.connect() as connection:
    schema = connection.execute("SELECT value FROM cmui_meta WHERE key='schema_version'").fetchone()[0]
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    foreign = len(connection.execute("PRAGMA foreign_key_check").fetchall())
if (schema, integrity, foreign) != ("13", "ok", 0):
    raise RuntimeError(f"Schema verification failed: schema={schema} integrity={integrity} foreign={foreign}")
print(f"MIGRATION=ok ui_schema={schema} integrity={integrity} foreign={foreign} routes={len(app.routes)}")
PY
migration_complete=1

set_current "$NEW_RELEASE"
switched=1
systemctl start coursemate-rag
systemctl start coursemate-agent

for _ in $(seq 1 30); do
  if curl --fail --silent --show-error --max-time 3 http://127.0.0.1:28000/health >/dev/null \
    && curl --fail --silent --show-error --max-time 3 http://127.0.0.1:28001/health >/dev/null; then
    break
  fi
  sleep 1
done
curl --fail --silent --show-error --max-time 3 http://127.0.0.1:28000/health >/dev/null
curl --fail --silent --show-error --max-time 3 http://127.0.0.1:28001/health >/dev/null
trap - ERR

printf 'RELEASE_SWITCH=ok current=%s config_backup=%s backup=%s\n' \
  "$(readlink -f "$CURRENT_LINK")" "$CONFIG_BACKUP" "$VERIFIED_BACKUP"
