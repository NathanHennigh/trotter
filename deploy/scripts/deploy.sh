#!/usr/bin/env bash
set -Eeuo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
ENV_FILE="$DEPLOY_DIR/home-server.env"
COMPOSE_FILE="$DEPLOY_DIR/compose.yml"
SECRETS_DIR="$DEPLOY_DIR/secrets"

for command_name in docker curl; do
  command -v "$command_name" >/dev/null 2>&1 || { echo "ERROR: $command_name is required." >&2; exit 1; }
done
docker compose version >/dev/null

[[ -f "$ENV_FILE" ]] || { echo "ERROR: Copy home-server.env.example to $ENV_FILE and edit it." >&2; exit 1; }
for secret_name in postgres_password google_client_secret jwt_secret encryption_key cloudflare_tunnel_token venice_api_key; do
  [[ -s "$SECRETS_DIR/$secret_name" ]] || { echo "ERROR: Missing secret: $SECRETS_DIR/$secret_name" >&2; exit 1; }
done

set -a
# shellcheck source=/dev/null
. "$ENV_FILE"
set +a

case "${TROTTER_API_URL:-}" in https://*) ;; *) echo 'ERROR: TROTTER_API_URL must use HTTPS.' >&2; exit 1 ;; esac
case "${TROTTER_WEB_URL:-}" in https://*) ;; *) echo 'ERROR: TROTTER_WEB_URL must use HTTPS.' >&2; exit 1 ;; esac

compose=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")
"${compose[@]}" config --quiet
"${compose[@]}" build
"${compose[@]}" rm -sf migrate >/dev/null 2>&1 || true
"${compose[@]}" up -d

api_port="${TROTTER_LOCAL_API_PORT:-8000}"
web_port="${TROTTER_LOCAL_WEB_PORT:-8080}"
deadline=$((SECONDS + 180))
until curl --fail --silent "http://127.0.0.1:$api_port/ready" >/dev/null \
  && curl --fail --silent "http://127.0.0.1:$web_port/health" >/dev/null; do
  if (( SECONDS >= deadline )); then
    "${compose[@]}" ps
    echo 'ERROR: Trotter did not become ready within three minutes.' >&2
    exit 1
  fi
  sleep 3
done

"${compose[@]}" ps
echo
echo "API ready: $TROTTER_API_URL"
echo "Web ready: $TROTTER_WEB_URL"
