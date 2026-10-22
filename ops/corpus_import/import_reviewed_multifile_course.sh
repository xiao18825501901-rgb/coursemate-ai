#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: import_reviewed_multifile_course.sh ROOT MANIFEST STATE" >&2
  exit 64
fi

root=$(readlink -f "$1")
manifest=$(readlink -f "$2")
state=$(readlink -m "$3")
volume_prefix=/srv/coursemate/data-volume/import-staging/
python_runtime=/srv/coursemate/runtime/rag-perf-5c134aa0eae4/bin/python
importer=${root}/import_reviewed_multifile_course.py
uploader=${root}/upload_presigned_put.py

[[ "${root}/" == "${volume_prefix}"* ]]
[[ -f "${manifest}" ]]
[[ -f "${importer}" ]]
[[ -f "${uploader}" ]]

exec 9>/run/lock/coursejesus-production-publish.lock
if ! flock -n 9; then
  echo "ERROR: shared production publish lock is held" >&2
  exit 75
fi
umask 077

if [[ ! -e "${state}" ]]; then
  backup_dir=/srv/coursemate/data-volume/release-backups/multifile-15s12-preimport-$(date -u +%Y%m%dT%H%M%SZ)
  mkdir -p "${backup_dir}"
  "${python_runtime}" - "${backup_dir}" <<'PY'
import hashlib, json, sqlite3, sys, time
from pathlib import Path

destination = Path(sys.argv[1]) / "rag.sqlite3"
source = Path("/srv/coursemate/data/releases/20260919T202006Z/rag.sqlite3")
with sqlite3.connect(source) as source_db, sqlite3.connect(destination) as backup_db:
    source_db.backup(backup_db)
with sqlite3.connect(destination) as check_db:
    integrity = check_db.execute("PRAGMA integrity_check").fetchone()[0]
    foreign_keys = check_db.execute("PRAGMA foreign_key_check").fetchall()
assert integrity == "ok" and not foreign_keys
hasher = hashlib.sha256()
with destination.open("rb") as handle:
    for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
        hasher.update(block)
receipt = {
    "source": str(source),
    "destination": str(destination),
    "bytes": destination.stat().st_size,
    "sha256": hasher.hexdigest(),
    "integrity_check": integrity,
    "foreign_key_violations": len(foreign_keys),
    "completed_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
}
(destination.parent / "BACKUP_RECEIPT.json").write_text(json.dumps(receipt, indent=2) + "\n")
print(json.dumps(receipt))
PY
  "${python_runtime}" "${importer}" prepare \
    --root "${root}" --manifest "${manifest}" --state "${state}"
fi

document_count=$("${python_runtime}" - "${state}" <<'PY'
import json, sys
print(len(json.load(open(sys.argv[1]))["documents"]))
PY
)

for ((index=0; index<document_count; index++)); do
  status=$("${python_runtime}" - "${state}" "${index}" <<'PY'
import json, sys
print(json.load(open(sys.argv[1]))["documents"][int(sys.argv[2])]["status"])
PY
)
  if [[ "${status}" == "READY" ]]; then
    continue
  fi
  if [[ "${status}" != "PLANNED" ]]; then
    echo "ERROR: slot ${index} is ${status}; reconcile it without issuing another grant" >&2
    exit 76
  fi
  source_file=$("${python_runtime}" - "${manifest}" "${index}" <<'PY'
import json, pathlib, sys
manifest = pathlib.Path(sys.argv[1])
item = json.load(open(manifest))["documents"][int(sys.argv[2])]
print((manifest.parent / item["relative_path"]).resolve())
PY
)
  grant_file=${root}/grant-${index}.json
  upload_receipt=${root}/upload-${index}.json
  [[ ! -e "${grant_file}" ]]
  [[ ! -e "${upload_receipt}" ]]
  "${python_runtime}" "${importer}" begin \
    --root "${root}" --manifest "${manifest}" --state "${state}" --index "${index}" \
    > "${grant_file}"
  "${python_runtime}" "${uploader}" --grant "${grant_file}" --file "${source_file}" \
    > "${upload_receipt}"
  upload_id=$("${python_runtime}" - "${grant_file}" <<'PY'
import json, sys
print(json.load(open(sys.argv[1]))["uploadId"])
PY
)
  "${python_runtime}" "${importer}" finalize \
    --root "${root}" --manifest "${manifest}" --state "${state}" \
    --index "${index}" --upload-id "${upload_id}"
  rm -f "${grant_file}"
done

"${python_runtime}" "${importer}" publish \
  --root "${root}" --manifest "${manifest}" --state "${state}"
curl -fsS --max-time 5 http://127.0.0.1:28000/health >/dev/null
curl -fsS --max-time 5 http://127.0.0.1:28001/health >/dev/null
cat "${state}"
