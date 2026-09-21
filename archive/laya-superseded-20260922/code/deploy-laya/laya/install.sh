#!/usr/bin/env bash
# CourseMate Laya inference service — node install.
# Idempotent. Run as root on the dedicated 8 vCPU / 16 GiB Ubuntu 24.04 node.
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-/srv/coursemate/current}"
APP_DIR="$REPO_ROOT/services/laya-inference"
RUNTIME_DIR="/srv/coursemate/runtime/laya"
MODEL_DIR="${LAY_MODEL_DIR:-/srv/coursemate/laya/multilingual}"
ENV_FILE="/etc/coursemate/laya.env"
DEFINITIONS_FILE="/etc/coursemate/laya-definitions.json"
SERVICE_USER="coursemate"

echo "==> Creating user and directories"
id -u "$SERVICE_USER" >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin "$SERVICE_USER"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 /srv/coursemate/laya
install -d -m 0750 /etc/coursemate

echo "==> Creating runtime venv (python3.12) and installing pinned deps"
python3.12 -m venv "$RUNTIME_DIR"
"$RUNTIME_DIR/bin/pip" install --upgrade pip
# Torch CPU wheel first so transformers/laya resolve against the CPU build.
"$RUNTIME_DIR/bin/pip" install torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu
"$RUNTIME_DIR/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "==> Fetching the pinned model snapshot (this step downloads ~647 MB)"
# Never 'latest': the pinned commit SHA is enforced inside the script.
"$RUNTIME_DIR/bin/python" "$REPO_ROOT/scripts/fetch_laya_model.py" --dest "$MODEL_DIR"

echo "==> Writing configuration (edit /etc/coursemate/laya.env before enabling)"
if [[ ! -f "$ENV_FILE" ]]; then
  install -o root -g root -m 0600 "$APP_DIR/../deploy/laya/laya.env.example" "$ENV_FILE"
  echo "    -> wrote $ENV_FILE (FILL IN LAYA_SERVICE_TOKEN)"
fi
if [[ ! -f "$DEFINITIONS_FILE" ]]; then
  install -o root -g root -m 0644 "$APP_DIR/../deploy/laya/laya-definitions.example.json" "$DEFINITIONS_FILE"
  echo "    -> wrote $DEFINITIONS_FILE (edit to the real allowlist)"
fi

echo "==> Installing and enabling systemd unit"
install -o root -g root -m 0644 "$APP_DIR/../deploy/laya/coursemate-laya.service" /etc/systemd/system/coursemate-laya.service
systemctl daemon-reload
systemctl enable coursemate-laya.service

echo "==> Done. Next steps:"
echo "    1. Edit $ENV_FILE and set LAYA_SERVICE_TOKEN."
echo "    2. systemctl start coursemate-laya.service"
echo "    3. bash $APP_DIR/../deploy/laya/smoke.sh"
