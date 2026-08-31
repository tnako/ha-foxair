#!/usr/bin/env bash
# Deploy local repo to HA host + restart core. No output except final check.
# Usage: HA_HOST=<ha-host> tools/deploy.sh   (env: HA_HOST required, HA_CC_PATH optional)
# Never hardcode the host here — this repo is public.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# auto-load .env (gitignored) if present, so you can run plain `tools/deploy.sh`
if [ -f "$REPO_ROOT/.env" ]; then
    set -a; . "$REPO_ROOT/.env"; set +a
fi
HA_HOST="${HA_HOST:?set HA_HOST (or create .env from .env.example)}"
HA_CC_PATH="${HA_CC_PATH:-/usr/share/hassio/homeassistant/custom_components}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
V=$(cat "$REPO/VERSION" | tr -d '[:space:]')

rsync -a --delete "$REPO/custom_components/foxair/" "root@$HA_HOST:$HA_CC_PATH/foxair/"
ssh "root@$HA_HOST" 'ha core restart >/dev/null 2>&1 &' || true

# Health check: wait for HA to fully respond (including API layer)
# Using /api/ on purpose: it returns 401 when the API is UP (needs auth)
# and returns nothing/connection-refused when the API stack is still starting.
for i in {1..60}; do
    code=$(curl -s -o /dev/null -w "%{http_code}" "http://$HA_HOST:8123/api/" 2>/dev/null || echo "000")
    if [ "$code" = "401" ] || [ "$code" = "200" ]; then
        echo "deployed $V to $HA_HOST — HA healthy"
        exit 0
    fi
    sleep 2
done
echo "deployed $V to $HA_HOST — WARNING: HA health check timed out (last code: $code)" >&2
exit 1