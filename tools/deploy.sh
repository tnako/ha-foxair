#!/usr/bin/env bash
# Deploy local repo to HA host + restart core. No output except final check.
# Usage: HA_HOST=<ha-host> tools/deploy.sh   (env: HA_HOST required, HA_CC_PATH optional)
# Never hardcode the host here — this repo is public.
set -euo pipefail
HA_HOST="${HA_HOST:?set HA_HOST to your HA host}"
HA_CC_PATH="${HA_CC_PATH:-/usr/share/hassio/homeassistant/custom_components}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
V=$(cat "$REPO/VERSION" | tr -d '[:space:]')

rsync -a --delete "$REPO/custom_components/foxair/" "root@$HA_HOST:$HA_CC_PATH/foxair/"
ssh "root@$HA_HOST" 'ha core restart >/dev/null 2>&1 &' || true
echo "deployed $V to $HA_HOST"