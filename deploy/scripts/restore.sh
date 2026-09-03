#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 2 || "$2" != '--confirm-replace-database' ]]; then
  echo "Usage: $0 /absolute/path/to/trotter.dump --confirm-replace-database" >&2
  exit 2
fi

BACKUP_FILE="$(realpath "$1")"
[[ -s "$BACKUP_FILE" ]] || { echo "ERROR: Backup not found or empty: $BACKUP_FILE" >&2; exit 1; }
DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
ENV_FILE="$DEPLOY_DIR/home-server.env"
COMPOSE_FILE="$DEPLOY_DIR/compose.yml"

set -a
# shellcheck source=/dev/null
. "$ENV_FILE"
set +a
compose=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")

"${compose[@]}" stop api worker
cat "$BACKUP_FILE" | "${compose[@]}" exec -T db pg_restore \
  --clean --if-exists --no-owner --no-privileges \
  --username "${POSTGRES_USER:-trotter}" \
  --dbname "${POSTGRES_DB:-trotter}"
"${compose[@]}" run --rm migrate
"${compose[@]}" up -d api worker
echo "Restored: $BACKUP_FILE"
