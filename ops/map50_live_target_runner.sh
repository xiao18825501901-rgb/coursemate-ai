#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: $0 <freeze|drain> <target-key> <inventory-jsonl>" >&2
  exit 64
fi

action=$1
target_key=$2
inventory_path=$3

case "$action" in
  freeze|drain) ;;
  *)
    echo "action must be freeze or drain" >&2
    exit 64
    ;;
esac

case "$target_key" in
  AUTO_COURSE:*|PRIVATE:*|SHARED:*) ;;
  *)
    echo "unsupported target-key namespace" >&2
    exit 64
    ;;
esac

case "$inventory_path" in
  /srv/coursemate/validation/map50-closeout-20260928T1510/*.jsonl) ;;
  *)
    echo "inventory path must stay inside the Map50 validation directory" >&2
    exit 64
    ;;
esac

set -a
. /etc/coursemate/rag.2d11587.env
. /etc/coursemate/secrets/p5-e0980c8.env
set +a

export AUTO_KNOWLEDGE_MAP_ENABLED=true
if [[ "$action" == "drain" ]]; then
  export AUTO_KNOWLEDGE_MAP_ALLOW_BILLABLE=true
  drain_args=(--drain --max-jobs 1)
else
  export AUTO_KNOWLEDGE_MAP_ALLOW_BILLABLE=false
  drain_args=()
fi

cd /srv/coursemate/current
stdout_path="${inventory_path%.jsonl}.stdout.log"
stderr_path="${inventory_path%.jsonl}.stderr.log"
sudo -E -u coursemate \
  /srv/coursemate/runtime/rag-e0980c8/bin/python \
  scripts/auto_knowledge_map_backfill.py \
  "${drain_args[@]}" \
  --target-key "$target_key" \
  --inventory "$inventory_path" \
  >"$stdout_path" 2>"$stderr_path"
