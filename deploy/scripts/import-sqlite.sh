#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 /absolute/path/to/trotter.db" >&2
  exit 2
fi

SQLITE_FILE="$(realpath "$1")"
[[ -s "$SQLITE_FILE" ]] || { echo "ERROR: SQLite database not found or empty: $SQLITE_FILE" >&2; exit 1; }
DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
ENV_FILE="$DEPLOY_DIR/home-server.env"
COMPOSE_FILE="$DEPLOY_DIR/compose.yml"
compose=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")
staged_file=/var/lib/trotter/sqlite-import/trotter.db

cleanup_staged_file() {
  "${compose[@]}" run --rm --no-deps --user root --entrypoint rm \
    api -f "$staged_file" >/dev/null 2>&1 || true
}

trap cleanup_staged_file EXIT

"${compose[@]}" build migrate
"${compose[@]}" up -d db redis
"${compose[@]}" run --rm migrate
"${compose[@]}" run --rm \
  --no-deps \
  --user root \
  --entrypoint install \
  --volume "$SQLITE_FILE:/migration/trotter.db:ro" \
  api -D -o trotter -g trotter -m 0400 /migration/trotter.db "$staged_file"
"${compose[@]}" run --rm --no-deps \
  api python -m scripts.migrate_sqlite_to_postgres --source "$staged_file"

cleanup_staged_file
trap - EXIT

echo 'SQLite data imported. Start the full stack with ./scripts/deploy.sh.'
