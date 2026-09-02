#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_NAME="backplane"
PUBLIC_SERVICE_NAME="backplane-public"
SERVICE_USER="${SUDO_USER:-$USER}"
LOG_DIR="${LOG_DIR:-/var/log/backplane}"
VAULT_DIR="${VAULT_DIR:-/root/obsidian/vaults/my-vault}"
OB_BIN="$(command -v ob || echo /usr/local/bin/ob)"
INSTALL_PUBLIC_MCP="${INSTALL_PUBLIC_MCP:-false}"
ENV_FILE="${INSTALL_DIR}/.env"

load_environment() {
    if [[ -f "${ENV_FILE}" ]]; then
        set -a
        # shellcheck disable=SC1090
        source "${ENV_FILE}"
        set +a
    fi
}

run_context_migrations() {
    if [[ -z "${CONTEXT_DATABASE_URL:-}" ]]; then
        echo "Context database is not configured; skipping Alembic migrations."
        return
    fi
    "$UV_BIN" run alembic upgrade head
}

# Install uv if not present
if ! command -v uv &>/dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi
UV_BIN="$(command -v uv 2>/dev/null || echo "$HOME/.local/bin/uv")"
load_environment

validate_public_mcp_oauth_config() {
    if [[ ! -f "${ENV_FILE}" ]]; then
        echo "Error: ${ENV_FILE} not found." >&2
        echo "Create it from .env.example and configure public MCP OAuth first." >&2
        exit 1
    fi

    if ! (
        cd "${INSTALL_DIR}"
        "$UV_BIN" run python -c "
from backplane.utils.settings import Settings

if not Settings().mcp_oauth_configured:
    raise SystemExit(1)
"
    ); then
        cat >&2 <<EOF
Error: INSTALL_PUBLIC_MCP=true requires these variables in ${ENV_FILE}:
  MCP_PUBLIC_BASE_URL
  MCP_OIDC_CONFIG_URL
  MCP_OIDC_CLIENT_ID
  MCP_OIDC_CLIENT_SECRET

Configure OAuth before enabling the public MCP service. See:
  .env.example
  deploy/authentik-backplane-mcp.env.example
EOF
        exit 1
    fi
}

install_public_mcp_systemd_units() {
    sed \
        -e "s|%%INSTALL_DIR%%|${INSTALL_DIR}|g" \
        -e "s|%%SERVICE_USER%%|${SERVICE_USER}|g" \
        -e "s|%%LOG_DIR%%|${LOG_DIR}|g" \
        "${INSTALL_DIR}/deploy/backplane-public.service.tmpl" \
        >"/etc/systemd/system/${PUBLIC_SERVICE_NAME}.service"

    sed \
        -e "s|%%LOG_DIR%%|${LOG_DIR}|g" \
        "${INSTALL_DIR}/deploy/backplane-public.logrotate.tmpl" \
        >"/etc/logrotate.d/${PUBLIC_SERVICE_NAME}"
}

# Install Python 3.14 + sync dependencies
cd "$INSTALL_DIR"
"$UV_BIN" python install 3.14
"$UV_BIN" sync --frozen --no-dev
run_context_migrations

install -d -o "${SERVICE_USER}" -m 0755 "${LOG_DIR}"

# Install systemd unit (substitute placeholders)
sed \
    -e "s|%%INSTALL_DIR%%|${INSTALL_DIR}|g" \
    -e "s|%%SERVICE_USER%%|${SERVICE_USER}|g" \
    -e "s|%%LOG_DIR%%|${LOG_DIR}|g" \
    "${INSTALL_DIR}/deploy/backplane.service.tmpl" \
    >"/etc/systemd/system/${SERVICE_NAME}.service"

# Install obsidian-sync unit (substitute placeholders)
sed \
    -e "s|%%INSTALL_DIR%%|${INSTALL_DIR}|g" \
    -e "s|%%SERVICE_USER%%|${SERVICE_USER}|g" \
    -e "s|%%LOG_DIR%%|${LOG_DIR}|g" \
    -e "s|%%VAULT_DIR%%|${VAULT_DIR}|g" \
    -e "s|/usr/bin/ob|${OB_BIN}|g" \
    "${INSTALL_DIR}/deploy/obsidian-sync.service.tmpl" \
    >"/etc/systemd/system/obsidian-sync.service"

# Install logrotate configs
sed \
    -e "s|%%LOG_DIR%%|${LOG_DIR}|g" \
    "${INSTALL_DIR}/deploy/backplane.logrotate.tmpl" \
    >"/etc/logrotate.d/${SERVICE_NAME}"
sed \
    -e "s|%%LOG_DIR%%|${LOG_DIR}|g" \
    "${INSTALL_DIR}/deploy/obsidian-sync.logrotate.tmpl" \
    >"/etc/logrotate.d/obsidian-sync"

if [[ "${INSTALL_PUBLIC_MCP}" == "true" ]]; then
    validate_public_mcp_oauth_config
    install_public_mcp_systemd_units
fi

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"
if [[ "${INSTALL_PUBLIC_MCP}" == "true" ]]; then
    systemctl enable "${PUBLIC_SERVICE_NAME}"
    systemctl restart "${PUBLIC_SERVICE_NAME}"
fi
systemctl enable obsidian-sync
systemctl restart obsidian-sync

echo "Services running:"
echo "  systemctl status ${SERVICE_NAME}"
if [[ "${INSTALL_PUBLIC_MCP}" == "true" ]]; then
    echo "  systemctl status ${PUBLIC_SERVICE_NAME}"
fi
echo "  systemctl status obsidian-sync"
