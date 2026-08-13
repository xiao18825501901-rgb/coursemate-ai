#!/usr/bin/env bash
set -euo pipefail

: "${RAG_DATABASE_PATH:?Set RAG_DATABASE_PATH}"
: "${RAG_UPLOAD_DIR:?Set RAG_UPLOAD_DIR}"
: "${BACKUP_ROOT:?Set BACKUP_ROOT to a dedicated backup directory}"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
destination="${BACKUP_ROOT%/}/coursemate-v2-${stamp}"
mkdir -m 700 -- "$destination"

# SQLite's online backup produces one consistent database image even in WAL mode.
sqlite3 "$RAG_DATABASE_PATH" ".timeout 10000" ".backup '$destination/rag.sqlite3'"
tar --create --gzip --file "$destination/uploads.tar.gz" --directory "$RAG_UPLOAD_DIR" .
sha256sum "$destination/rag.sqlite3" "$destination/uploads.tar.gz" > "$destination/SHA256SUMS"
sqlite3 "$destination/rag.sqlite3" "PRAGMA integrity_check; PRAGMA foreign_key_check;" \
  > "$destination/sqlite-check.txt"

printf '%s\n' "$destination"
