#!/usr/bin/env bash
# Create a verified CourseMate recovery unit during one short writer pause.
# Run only as root on the confirmed production host. It deliberately preserves
# a failed backup directory and restores only the services that were active
# before the window; it never deletes data or overwrites a backup.
set -euo pipefail

: "${BACKUP_ROOT:?Set BACKUP_ROOT to a dedicated directory outside uploads}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RAG_ENV="${RAG_ENV:-/etc/coursemate/rag.env}"
AGENT_ENV="${AGENT_ENV:-/etc/coursemate/agent.env}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [[ "$(id -u)" != "0" ]]; then
  echo "Run this production backup window as root." >&2
  exit 2
fi
[[ -r "$RAG_ENV" && -r "$AGENT_ENV" ]] || {
  echo "Required CourseMate environment file is unreadable." >&2
  exit 2
}
[[ -x "$PYTHON_BIN" ]] || {
  echo "Configured Python runtime is not executable." >&2
  exit 2
}

rag_was_active=0
agent_was_active=0
systemctl is-active --quiet coursemate-rag && rag_was_active=1 || true
systemctl is-active --quiet coursemate-agent && agent_was_active=1 || true

restore_services() {
  local code=$?
  if [[ "$rag_was_active" == "1" || "$agent_was_active" == "1" ]]; then
    if [[ "$rag_was_active" == "1" ]]; then systemctl start coursemate-rag; fi
    if [[ "$agent_was_active" == "1" ]]; then systemctl start coursemate-agent; fi
  fi
  exit "$code"
}
trap restore_services EXIT

install -d -m 700 "$BACKUP_ROOT"
systemctl stop coursemate-agent coursemate-rag

# Environment files are trusted root-owned configuration. Export them only to
# the project backup process; never echo their values.
set -a
# shellcheck disable=SC1090
. "$RAG_ENV"
# shellcheck disable=SC1090
. "$AGENT_ENV"
set +a
export BACKUP_ROOT

backup_path="$($PYTHON_BIN "$SCRIPT_DIR/backup_v2.py")"

if [[ "$rag_was_active" == "1" ]]; then systemctl start coursemate-rag; fi
if [[ "$agent_was_active" == "1" ]]; then systemctl start coursemate-agent; fi
trap - EXIT

for _ in $(seq 1 30); do
  if curl --fail --silent --show-error --max-time 3 http://127.0.0.1:28000/health >/dev/null \
    && curl --fail --silent --show-error --max-time 3 http://127.0.0.1:28001/health >/dev/null; then
    printf 'VERIFIED_BACKUP=%s\n' "$backup_path"
    exit 0
  fi
  sleep 1
done

echo "Backup completed, but restarted service health did not recover within 30 seconds." >&2
exit 3
