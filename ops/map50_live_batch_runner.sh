#!/usr/bin/env bash
set -uo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 <target-manifest> <batch-label>" >&2
  exit 64
fi

manifest=$1
batch_label=$2
validation_root=/srv/coursemate/validation/map50-closeout-20260928T1510
target_runner="$validation_root/map50_live_target_runner.sh"

case "$manifest" in
  "$validation_root"/*.targets) ;;
  *)
    echo "target manifest must stay inside the Map50 validation directory" >&2
    exit 64
    ;;
esac
if [[ ! "$batch_label" =~ ^[a-z0-9-]{1,40}$ ]]; then
  echo "batch label must contain only lowercase letters, digits, and hyphens" >&2
  exit 64
fi
if [[ ! -r "$manifest" || ! -x "$target_runner" ]]; then
  echo "manifest or target runner is unavailable" >&2
  exit 66
fi

failures=0
ordinal=0
while IFS= read -r target_key || [[ -n "$target_key" ]]; do
  [[ -z "$target_key" || "$target_key" == \#* ]] && continue
  case "$target_key" in
    AUTO_COURSE:*|PRIVATE:*|SHARED:*) ;;
    *)
      echo "INVALID_TARGET ordinal=$ordinal" >&2
      failures=$((failures + 1))
      ordinal=$((ordinal + 1))
      continue
      ;;
  esac
  key_hash=$(printf '%s' "$target_key" | sha256sum | cut -c1-12)
  prefix="$validation_root/${batch_label}-${ordinal}-${key_hash}"
  echo "MAP50_TARGET_START ordinal=$ordinal key_hash=$key_hash"
  if ! "$target_runner" freeze "$target_key" "${prefix}-freeze.jsonl"; then
    echo "MAP50_TARGET_FREEZE_FAILED ordinal=$ordinal key_hash=$key_hash" >&2
    failures=$((failures + 1))
    ordinal=$((ordinal + 1))
    continue
  fi
  if ! "$target_runner" drain "$target_key" "${prefix}-live.jsonl"; then
    echo "MAP50_TARGET_DRAIN_FAILED ordinal=$ordinal key_hash=$key_hash" >&2
    failures=$((failures + 1))
  else
    echo "MAP50_TARGET_FINISHED ordinal=$ordinal key_hash=$key_hash"
  fi
  ordinal=$((ordinal + 1))
done <"$manifest"

echo "MAP50_BATCH_FINISHED targets=$ordinal runner_failures=$failures"
exit "$failures"
