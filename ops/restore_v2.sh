#!/usr/bin/env bash
set -euo pipefail

: "${RESTORE_SOURCE:?Set RESTORE_SOURCE to one verified backup directory}"
: "${RESTORE_TARGET:?Set RESTORE_TARGET to a NEW, empty rehearsal directory}"

if [[ -e "$RESTORE_TARGET" ]]; then
  printf 'Refusing to overwrite existing restore target: %s\n' "$RESTORE_TARGET" >&2
  exit 2
fi

(cd "$RESTORE_SOURCE" && sha256sum --check SHA256SUMS)
mkdir -m 700 -- "$RESTORE_TARGET" "$RESTORE_TARGET/uploads"
cp -- "$RESTORE_SOURCE/rag.sqlite3" "$RESTORE_TARGET/rag.sqlite3"
tar --extract --gzip --file "$RESTORE_SOURCE/uploads.tar.gz" \
  --directory "$RESTORE_TARGET/uploads"
sqlite3 "$RESTORE_TARGET/rag.sqlite3" \
  "PRAGMA integrity_check; PRAGMA foreign_key_check; SELECT version,name FROM schema_migrations ORDER BY version;"

printf 'Isolated restore ready at %s\n' "$RESTORE_TARGET"
