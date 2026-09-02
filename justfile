set dotenv-load

# List available recipes
default:
    @just --list

# Restart the private MCP server (systemd when installed, otherwise a local background process)
[private]
_mcp-restart:
    #!/usr/bin/env bash
    set -euo pipefail
    if systemctl cat backplane.service &>/dev/null; then
        systemctl restart backplane
        systemctl is-active --quiet backplane
        echo "MCP server restarted via systemd (backplane.service)"
    else
        pkill -f "backplane.mcp" || true
        nohup uv run python -m backplane.mcp >> /tmp/backplane-mcp.log 2>&1 &
        echo "MCP server started (PID $!), logging to /tmp/backplane-mcp.log"
    fi

# Restart the public MCP server (systemd when installed, otherwise a local background process)
[private]
_mcp-public-restart:
    #!/usr/bin/env bash
    set -euo pipefail
    if systemctl cat backplane-public.service &>/dev/null; then
        systemctl restart backplane-public
        systemctl is-active --quiet backplane-public
        echo "Public MCP server restarted via systemd (backplane-public.service)"
    else
        pkill -f "backplane.mcp.public" || true
        nohup uv run python -m backplane.mcp.public >> /tmp/backplane-public-mcp.log 2>&1 &
        echo "Public MCP server started (PID $!), logging to /tmp/backplane-public-mcp.log"
    fi

# Apply context-capture migrations when persistence is configured
[private]
_context-migrate:
    #!/usr/bin/env bash
    set -euo pipefail
    if [[ -z "${CONTEXT_DATABASE_URL:-}" ]]; then
        echo "Context database is not configured; skipping Alembic migrations."
        exit 0
    fi
    uv run alembic upgrade head

# Start or restart the private MCP server
mcp-start:
    just _mcp-restart

# Start or restart the public MCP server
mcp-public-start:
    just _mcp-public-restart

# Stop the private MCP server
mcp-stop:
    #!/usr/bin/env bash
    if systemctl cat backplane.service &>/dev/null; then
        systemctl stop backplane
        echo "MCP server stopped (backplane.service)"
    elif pkill -f "backplane.mcp"; then
        echo "MCP server stopped"
    else
        echo "MCP server was not running"
    fi

# Stop the public MCP server
mcp-public-stop:
    #!/usr/bin/env bash
    if systemctl cat backplane-public.service &>/dev/null; then
        systemctl stop backplane-public
        echo "Public MCP server stopped (backplane-public.service)"
    elif pkill -f "backplane.mcp.public"; then
        echo "Public MCP server stopped"
    else
        echo "Public MCP server was not running"
    fi

# Tail private MCP server logs
mcp-logs lines="100":
    #!/usr/bin/env bash
    if systemctl cat backplane.service &>/dev/null; then
        tail -f /var/log/backplane/backplane.log -n "{{ lines }}"
    else
        tail -f /tmp/backplane-mcp.log -n "{{ lines }}"
    fi

# Tail public MCP server logs
mcp-public-logs lines="100":
    #!/usr/bin/env bash
    if systemctl cat backplane-public.service &>/dev/null; then
        tail -f /var/log/backplane/backplane-public.log -n "{{ lines }}"
    else
        tail -f /tmp/backplane-public-mcp.log -n "{{ lines }}"
    fi

# Install systemd units, logrotate configs, and service dependencies
setup log_dir="/var/log/backplane":
    #!/usr/bin/env bash
    set -euo pipefail
    if [[ "$(id -u)" -eq 0 ]]; then
        env LOG_DIR="{{ log_dir }}" ./deploy/setup.sh
    else
        sudo env LOG_DIR="{{ log_dir }}" ./deploy/setup.sh
    fi

# Checkout a specific tag, sync deps, and restart via systemd — called by CI
deploy tag:
    git fetch --tags origin
    git reset --hard {{ tag }}
    uv sync --frozen --no-dev
    just _context-migrate
    just _mcp-restart
    if systemctl is-enabled backplane-public.service &>/dev/null; then just _mcp-public-restart; fi

# Checkout a branch, sync deps, and restart the MCP servers
checkout branch="main":
    git fetch origin
    git checkout {{ branch }}
    git pull
    uv sync --no-dev
    just _context-migrate
    just _mcp-restart
    if systemctl is-enabled backplane-public.service &>/dev/null; then just _mcp-public-restart; fi

# Pull the current branch, sync deps, and restart the MCP servers
pull:
    #!/usr/bin/env bash
    set -euo pipefail
    branch="$(git branch --show-current)"
    if [[ -z "${branch}" ]]; then
        echo "Cannot pull: HEAD is detached"
        exit 1
    fi
    just checkout "${branch}"
