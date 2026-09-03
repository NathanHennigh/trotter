#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "ERROR: This bootstrap script requires Linux." >&2
  exit 1
fi

if [[ "$(id -u)" -eq 0 ]]; then
  SUDO=()
elif command -v sudo >/dev/null 2>&1; then
  SUDO=(sudo)
else
  echo "ERROR: Run as root or install sudo." >&2
  exit 1
fi

"${SUDO[@]}" apt-get update
"${SUDO[@]}" apt-get install -y ca-certificates curl git

if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
  "${SUDO[@]}" sh /tmp/get-docker.sh
  rm -f /tmp/get-docker.sh
fi

"${SUDO[@]}" systemctl enable --now docker

if [[ "$(id -u)" -ne 0 ]] && ! id -nG "$USER" | tr ' ' '\n' | grep -qx docker; then
  "${SUDO[@]}" usermod -aG docker "$USER"
  echo "Docker installed. Sign out and back in, then rerun this script."
  exit 0
fi

docker compose version >/dev/null
echo "OCI host is ready: $(uname -m), Docker $(docker version --format '{{.Server.Version}}')"
