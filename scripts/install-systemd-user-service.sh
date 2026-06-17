#!/usr/bin/env bash
# Install MAMArr as a systemd user service (streamable-http transport via uv).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="mamarr-mcp.service"
TEMPLATE="${REPO_ROOT}/deploy/systemd/${SERVICE_NAME}"
USER_UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
DEST="${USER_UNIT_DIR}/${SERVICE_NAME}"

UV_BIN="$(command -v uv || true)"
if [[ -z "${UV_BIN}" ]]; then
  echo "error: uv not found in PATH. Install: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

if [[ ! -f "${REPO_ROOT}/.env" ]]; then
  echo "warning: ${REPO_ROOT}/.env not found — copy env.example to .env and configure it." >&2
fi

if [[ ! -f "${REPO_ROOT}/pyproject.toml" ]]; then
  echo "error: pyproject.toml not found in ${REPO_ROOT}" >&2
  exit 1
fi

echo "Syncing dependencies with uv..."
(cd "${REPO_ROOT}" && uv sync)

mkdir -p "${USER_UNIT_DIR}"

sed \
  -e "s|%MAMARR_DIR%|${REPO_ROOT}|g" \
  -e "s|%UV_BIN%|${UV_BIN}|g" \
  "${TEMPLATE}" > "${DEST}"

echo "Installed ${DEST}"

if systemctl --user daemon-reload 2>/dev/null; then
  echo "Reloaded systemd user daemon."
else
  echo "note: systemd user session unavailable here — run 'systemctl --user daemon-reload' on your host." >&2
fi

echo ""
echo "Enable and start:"
echo "  systemctl --user enable --now ${SERVICE_NAME}"
echo ""
echo "Check status:"
echo "  systemctl --user status ${SERVICE_NAME}"
echo "  journalctl --user -u ${SERVICE_NAME} -f"
echo ""
echo "Run at boot without an active login session (recommended for servers):"
echo "  loginctl enable-linger \"${USER}\""
