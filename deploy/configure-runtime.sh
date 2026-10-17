#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# A drop-in keeps application settings independent of provisioned service units.
for service in backplane backplane-public; do
    directory="/etc/systemd/system/${service}.service.d"
    install -d -m 0755 "$directory"
    printf '[Service]\nEnvironmentFile=%s/deploy/runtime.env\n' "$INSTALL_DIR" \
        > "$directory/50-runtime.conf"
done

systemctl daemon-reload
