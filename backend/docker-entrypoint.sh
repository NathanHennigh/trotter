#!/bin/sh
set -eu

load_secret() {
  variable_name="$1"
  file_variable_name="$2"
  file_path="$(printenv "$file_variable_name" 2>/dev/null || true)"
  if [ -n "$file_path" ]; then
    if [ ! -r "$file_path" ]; then
      echo "ERROR: Secret file is not readable: $file_path" >&2
      exit 1
    fi
    value="$(cat "$file_path")"
    export "$variable_name=$value"
  fi
}

load_secret POSTGRES_PASSWORD POSTGRES_PASSWORD_FILE
load_secret GOOGLE_CLIENT_SECRET GOOGLE_CLIENT_SECRET_FILE
load_secret JWT_SECRET JWT_SECRET_FILE
load_secret ENCRYPTION_KEY ENCRYPTION_KEY_FILE
load_secret VENICE_API_KEY VENICE_API_KEY_FILE

if [ -z "${DATABASE_URL:-}" ]; then
  if [ -z "${POSTGRES_PASSWORD:-}" ]; then
    echo 'ERROR: DATABASE_URL or POSTGRES_PASSWORD_FILE is required.' >&2
    exit 1
  fi
  encoded_password="$(python -c 'import os, urllib.parse; print(urllib.parse.quote(os.environ["POSTGRES_PASSWORD"], safe=""))')"
  export DATABASE_URL="postgresql+psycopg://${POSTGRES_USER:-trotter}:$encoded_password@${POSTGRES_HOST:-db}:${POSTGRES_PORT:-5432}/${POSTGRES_DB:-trotter}"
fi

if [ "$(id -u)" -eq 0 ]; then
  exec gosu trotter "$@"
fi

exec "$@"
