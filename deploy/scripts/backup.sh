#!/usr/bin/env bash
set -Eeuo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
ENV_FILE="$DEPLOY_DIR/home-server.env"
BACKUP_DIR="$DEPLOY_DIR/backups"
COMPOSE_FILE="$DEPLOY_DIR/compose.yml"

[[ -f "$ENV_FILE" ]] || { echo "ERROR: Missing $ENV_FILE" >&2; exit 1; }
set -a
# shellcheck source=/dev/null
. "$ENV_FILE"
set +a

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
stamp="$(date -u +%Y-%m-%d_%H-%M-%SZ)"
target="$BACKUP_DIR/trotter-$stamp.dump"
tmp="$target.tmp"
compose=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")

"${compose[@]}" exec -T db pg_dump \
  --username "${POSTGRES_USER:-trotter}" \
  --dbname "${POSTGRES_DB:-trotter}" \
  --format custom > "$tmp"

[[ -s "$tmp" ]] || { rm -f "$tmp"; echo 'ERROR: pg_dump produced an empty backup.' >&2; exit 1; }
mv "$tmp" "$target"
sha256sum "$target" > "$target.sha256"
chmod 600 "$target" "$target.sha256"
echo "Saved: $target"
