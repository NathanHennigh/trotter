#!/usr/bin/env bash
set -Eeuo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
SECRETS_DIR="$DEPLOY_DIR/secrets"

command -v openssl >/dev/null 2>&1 || { echo 'ERROR: openssl is required.' >&2; exit 1; }
mkdir -p "$SECRETS_DIR"
chmod 700 "$SECRETS_DIR"
umask 077

write_if_missing() {
  local path="$1"
  local value="$2"
  if [[ ! -s "$path" ]]; then
    printf '%s' "$value" > "$path"
    echo "Created: $path"
  else
    echo "Kept existing: $path"
  fi
}

write_if_missing "$SECRETS_DIR/postgres_password" "$(openssl rand -hex 32)"
write_if_missing "$SECRETS_DIR/jwt_secret" "$(openssl rand -hex 32)"
write_if_missing "$SECRETS_DIR/encryption_key" "$(openssl rand -base64 32)"

for required_secret in google_client_secret cloudflare_tunnel_token; do
  if [[ ! -e "$SECRETS_DIR/$required_secret" ]]; then
    : > "$SECRETS_DIR/$required_secret"
    echo "Created empty placeholder: $SECRETS_DIR/$required_secret"
  fi
done

chmod 600 "$SECRETS_DIR"/*
echo 'Fill google_client_secret and cloudflare_tunnel_token before deployment.'
