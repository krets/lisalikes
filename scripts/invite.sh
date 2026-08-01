#!/bin/bash
# Send a curator magic-link invite, reading ADMIN_SECRET / APP_DOMAIN from .env.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -z "${1:-}" ]; then
    echo "Usage: $0 <email>" >&2
    exit 1
fi

set -a
source .env
set +a

curl -X POST "${APP_DOMAIN}/api/admin/invite?secret=${ADMIN_SECRET}" \
    -H "Content-Type: application/json" \
    -d "{\"email\": \"$1\"}"
echo
