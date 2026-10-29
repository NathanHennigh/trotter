#!/usr/bin/env bash
set -Eeuo pipefail

ACTION="${1:-help}"
REPO_INPUT="${2:-~/Developer/trotter-build}"
REPO_URL="${3:-https://github.com/NathanHennigh/trotter.git}"
BRANCH="${4:-main}"
EXPECTED_COMMIT="${5:-}"
PROFILE="${6:-iphone-testflight}"
ARTIFACTS_INPUT="${7:-~/TrotterBuilds}"
EAS_VERSION="${8:-21.7.1}"
ASC_KEY_ID_INPUT="${9:-}"
ASC_ISSUER_ID_INPUT="${10:-}"
ASC_STAGING_NAME_INPUT="${11:-}"
SELF="$HOME/.trotter-ios-remote/ios-remote.sh"
IPA_VERIFY_HELPER="$HOME/.trotter-ios-remote/verify-production-ipa.sh"
LOCAL_BUILD_PLUGIN_VERSION="21.6.0"
LOCAL_BUILD_PLUGIN_ROOT="$HOME/.trotter-ios-remote/tooling/eas-local-build-plugin-$LOCAL_BUILD_PLUGIN_VERSION"
LOCAL_BUILD_PLUGIN_BIN="$LOCAL_BUILD_PLUGIN_ROOT/node_modules/eas-cli-local-build-plugin/bin/run"
WWDR_G3_SHA1="06EC06599F4ED0027CC58956B4D3AC1255114F35"
LOCAL_BUILD_SESSION="trotter-ios-local"
LOCAL_BUILD_RESULT="$HOME/.trotter-ios-remote/local-build.result"
DIRECT_SUBMIT_CONFIG="$HOME/.trotter-ios-remote/app-store-connect.conf"
DIRECT_SUBMIT_RESULT="$HOME/.trotter-ios-remote/direct-submit.result"
DIRECT_SUBMIT_LOCK="$HOME/.trotter-ios-remote/direct-submit.lock"
DIRECT_SUBMIT_RECEIPTS="$HOME/.trotter-ios-remote/direct-submit-receipts"
DIRECT_SUBMIT_BUILDS="$HOME/.trotter-ios-remote/direct-submit-builds"
DIRECT_CONFIG_LOCK="$HOME/.trotter-ios-remote/direct-config.lock"
ASC_KEY_ID=""
ASC_ISSUER_ID=""
ASC_KEY_PATH=""

expand_home() {
  local value="$1"
  if [[ "$value" == "~/"* ]]; then
    printf '%s/%s' "$HOME" "${value:2}"
  else
    printf '%s' "$value"
  fi
}

REPO="$(expand_home "$REPO_INPUT")"
ARTIFACTS="$(expand_home "$ARTIFACTS_INPUT")"
APP="$REPO/mobile-v2"
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8

# SSH non-login shells often omit Homebrew and version-manager paths.
export PATH="/opt/homebrew/opt/node@22/bin:/usr/local/opt/node@22/bin:/opt/homebrew/bin:/usr/local/bin:$HOME/.volta/bin:$HOME/.local/bin:$PATH"
if [[ -s "$HOME/.nvm/nvm.sh" ]]; then
  # shellcheck disable=SC1090
  source "$HOME/.nvm/nvm.sh"
fi
if command -v fnm >/dev/null 2>&1; then
  eval "$(fnm env --shell bash)"
fi
if [[ -x "$HOME/.local/share/mise/shims/node" ]]; then
  export PATH="$HOME/.local/share/mise/shims:$PATH"
fi

say() {
  printf '\n==> %s\n' "$*"
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "Missing '$1'. $2"
}

assert_trotter_paths() {
  # These paths are deliberately fixed so a config typo cannot reset another
  # application's clone, replace its helpers, or mix its release artifacts.
  [[ "$ARTIFACTS" == "$HOME/TrotterBuilds" && ! -L "$ARTIFACTS" ]] || die "MacArtifacts must be ~/TrotterBuilds."
  [[ ! -L "$HOME/.trotter-ios-remote" ]] || die "The Trotter helper directory cannot be a symlink."
  case "$ACTION" in
    simulator-snapshot|snapshot-status|snapshot-latest-artifact)
      [[ "$EXPECTED_COMMIT" =~ ^[a-f0-9]{64}$ && "$REPO" == "$HOME/.trotter-ios-remote/snapshots/$EXPECTED_COMMIT" && "$PROFILE" == iphone-simulator ]] || die "Invalid simulator snapshot arguments."
      ;;
    *) [[ "$REPO" == "$HOME/Developer/trotter-build" && ! -L "$REPO" && ! -L "$HOME/Developer" ]] || die "MacRepo must be ~/Developer/trotter-build." ;;
  esac
  [[ "$REPO_URL" == https://github.com/NathanHennigh/trotter.git ]] || die "The build repository must be NathanHennigh/trotter."
  case "$PROFILE" in iphone-simulator|iphone-development|iphone-testflight) ;; *) die "Unsupported iPhone build profile: $PROFILE" ;; esac
}

load_build_environment() {
  local file="$HOME/.trotter-ios-remote/build.env" line key value
  [[ -e "$file" ]] || return 0
  assert_private_file "$file" "Trotter build environment"
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    [[ -z "$line" || "$line" == \#* ]] && continue
    key="${line%%=*}"; value="${line#*=}"
    case "$key" in EXPO_PUBLIC_TROTTER_API_URL|EXPO_PUBLIC_APPLE_SIGN_IN_ENABLED|GOOGLE_MAPS_IOS_API_KEY|APPLE_TEAM_ID|APPLE_APP_ID_PREFIX|EAS_PROJECT_ID) ;; *) die "Unsupported key in build.env." ;; esac
    [[ "$line" == *=* && "$value" != \"* && "$value" != \'* ]] || die "Use unquoted KEY=value lines in build.env."
    export "$key=$value"
  done < "$file"
}

eas() {
  npx --yes "eas-cli@$EAS_VERSION" "$@"
}

assert_node_version() {
  require_command node "Install Node 22 for the dedicated build user."
  node -e '
    const [major, minor, patch] = process.versions.node.split(".").map(Number);
    const ok = major > 20 || (major === 20 && (minor > 19 || (minor === 19 && patch >= 4)));
    if (!ok) {
      console.error(`Node ${process.versions.node} is too old; Trotter requires >=20.19.4 (Node 22 recommended).`);
      process.exit(1);
    }
  '
}

assert_repo_exists() {
  [[ -d "$REPO/.git" ]] || die "Build clone is missing at $REPO. Run the setup action first."

  local actual_remote
  actual_remote="$(git -C "$REPO" remote get-url origin)"
  [[ "$actual_remote" == "$REPO_URL" ]] || \
    die "Build clone origin is $actual_remote, expected $REPO_URL. Update config or use a new dedicated clone path."
}

assert_repo_clean_at_commit() {
  [[ "$EXPECTED_COMMIT" =~ ^[a-f0-9]{40}$ ]] || die "A full pushed Git commit SHA is required."
  assert_repo_exists
  cd "$REPO"

  local status actual
  status="$(git status --porcelain --untracked-files=all)"
  [[ -z "$status" ]] || die "Mac build clone is dirty. It was left untouched:\n$status"

  actual="$(git rev-parse HEAD)"
  [[ -n "$EXPECTED_COMMIT" && "$actual" == "$EXPECTED_COMMIT" ]] || \
    die "Mac checkout is $actual, expected $EXPECTED_COMMIT. Run sync again."
}

sync_exact_commit() {
  require_command git "Install the Xcode Command Line Tools."
  [[ "$EXPECTED_COMMIT" =~ ^[a-f0-9]{40}$ ]] || die "A full pushed Git commit SHA is required."
  git check-ref-format --branch "$BRANCH" >/dev/null || die "Invalid branch name."
  assert_repo_exists
  cd "$REPO"

  local status remote_commit
  status="$(git status --porcelain --untracked-files=all)"
  [[ -z "$status" ]] || die "Mac build clone is dirty, so sync stopped without changing it:\n$status"

  say "Fetching origin/$BRANCH"
  git fetch --prune origin "+refs/heads/$BRANCH:refs/remotes/origin/$BRANCH"
  remote_commit="$(git rev-parse "origin/$BRANCH")"
  [[ "$remote_commit" == "$EXPECTED_COMMIT" ]] || \
    die "origin/$BRANCH is $remote_commit on the Mac, not expected $EXPECTED_COMMIT."

  git switch --detach "$EXPECTED_COMMIT"
  [[ -z "$(git status --porcelain --untracked-files=all)" ]] || \
    die "Checkout became dirty unexpectedly; stopping."
  printf 'Mac build clone is pinned to %s (%s).\n' "$EXPECTED_COMMIT" "$BRANCH"
}

doctor_cloud() {
  local failed=0
  say "Cloud-build trigger requirements"
  for cmd in git node npm npx; do
    if command -v "$cmd" >/dev/null 2>&1; then
      printf '%-14s %s\n' "$cmd" "$(command -v "$cmd")"
    else
      printf '%-14s MISSING\n' "$cmd"
      failed=1
    fi
  done

  if command -v node >/dev/null 2>&1; then
    node --version
    assert_node_version || failed=1
  fi
  if command -v npm >/dev/null 2>&1; then
    npm --version
  fi

  sw_vers
  df -h "$HOME" | tail -n 1

  say "Expo account"
  if ! eas whoami; then
    printf 'Not logged into Expo yet. Run the eas-login action.\n'
    failed=1
  fi

  [[ "$failed" -eq 0 ]] || die "Cloud-build doctor found missing requirements."
}

doctor_local() {
  doctor_cloud
  local failed=0

  say "Mac-local iOS build requirements"
  if xcode-select -p >/dev/null 2>&1; then
    xcode-select -p
  else
    printf 'Xcode command-line tools: MISSING\n'
    failed=1
  fi

  if command -v xcodebuild >/dev/null 2>&1; then
    xcodebuild -version
    if ! xcodebuild -checkFirstLaunchStatus >/dev/null 2>&1; then
      printf 'Xcode first-launch/license setup is incomplete.\n'
      failed=1
    fi
  else
    printf 'xcodebuild: MISSING\n'
    failed=1
  fi

  for cmd in pod fastlane caffeinate; do
    if command -v "$cmd" >/dev/null 2>&1; then
      printf '%-14s %s\n' "$cmd" "$(command -v "$cmd")"
    else
      printf '%-14s MISSING\n' "$cmd"
      failed=1
    fi
  done

  if command -v tmux >/dev/null 2>&1; then
    printf '%-14s %s\n' "tmux" "$(command -v tmux)"
  else
    printf '%-14s OPTIONAL (recommended so a dropped SSH session does not stop a local build)\n' "tmux"
  fi

  if [[ "$PROFILE" != "iphone-simulator" ]]; then
    local wwdr_certificates
    wwdr_certificates="$(/usr/bin/security find-certificate -a -Z \
      -c "Apple Worldwide Developer Relations Certification Authority" \
      /Library/Keychains/System.keychain 2>/dev/null || true)"
    if grep -q "$WWDR_G3_SHA1" <<<"$wwdr_certificates"; then
      printf '%-14s %s\n' "WWDR G3" "$WWDR_G3_SHA1"
    else
      printf '%-14s MISSING from /Library/Keychains/System.keychain\n' "WWDR G3"
      printf 'Install Apple WWDR G3 once from an administrator account before a signed local build.\n'
      failed=1
    fi
  fi

  [[ "$failed" -eq 0 ]] || die "Local-build doctor found missing requirements."
}

validate_asc_key_id() {
  [[ "$1" =~ ^[A-Z0-9]{10}$ ]]
}

validate_asc_issuer_id() {
  [[ "$1" =~ ^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$ ]]
}

direct_config_value() {
  local key="$1"
  awk -F= -v wanted="$key" '
    $1 == wanted {
      count += 1
      value = substr($0, index($0, "=") + 1)
    }
    END {
      if (count != 1) exit 1
      print value
    }
  ' "$DIRECT_SUBMIT_CONFIG"
}

assert_private_file() {
  local path="$1" label="$2" owner mode
  [[ -f "$path" && ! -L "$path" ]] || die "$label is missing or is not a regular file: $path"
  owner="$(stat -f '%Su' "$path")"
  mode="$(stat -f '%Lp' "$path")"
  [[ "$owner" == "$(id -un)" ]] || die "$label is owned by $owner, not $(id -un)."
  [[ "$mode" == "600" ]] || die "$label permissions are $mode; expected 600."
}

assert_private_directory() {
  local path="$1" label="$2" owner mode
  [[ -d "$path" && ! -L "$path" ]] || die "$label is missing or is not a regular directory: $path"
  owner="$(stat -f '%Su' "$path")"
  mode="$(stat -f '%Lp' "$path")"
  [[ "$owner" == "$(id -un)" ]] || die "$label is owned by $owner, not $(id -un)."
  [[ "$mode" == "700" ]] || die "$label permissions are $mode; expected 700."
}

load_direct_submit_config() {
  assert_private_directory "$HOME/.trotter-ios-remote" "Direct-submit configuration directory"
  assert_private_file "$DIRECT_SUBMIT_CONFIG" "Direct-submit configuration"
  ASC_KEY_ID="$(direct_config_value ASC_KEY_ID)" || \
    die "Direct-submit configuration must contain exactly one ASC_KEY_ID."
  ASC_ISSUER_ID="$(direct_config_value ASC_ISSUER_ID)" || \
    die "Direct-submit configuration must contain exactly one ASC_ISSUER_ID."
  validate_asc_key_id "$ASC_KEY_ID" || die "Configured App Store Connect Key ID is invalid."
  validate_asc_issuer_id "$ASC_ISSUER_ID" || die "Configured App Store Connect Issuer ID is invalid."

  ASC_KEY_PATH="$HOME/.appstoreconnect/private_keys/AuthKey_$ASC_KEY_ID.p8"
  assert_private_directory "$HOME/.appstoreconnect" "App Store Connect directory"
  assert_private_directory "$HOME/.appstoreconnect/private_keys" "App Store Connect private-key directory"
  assert_private_file "$ASC_KEY_PATH" "App Store Connect private key"
  grep -qx -- '-----BEGIN PRIVATE KEY-----' "$ASC_KEY_PATH" || \
    die "App Store Connect key has an invalid PKCS#8 header."
  grep -qx -- '-----END PRIVATE KEY-----' "$ASC_KEY_PATH" || \
    die "App Store Connect key has an invalid PKCS#8 footer."
  /usr/bin/openssl pkey -in "$ASC_KEY_PATH" -noout >/dev/null 2>&1 || \
    die "App Store Connect private key could not be parsed."
}

verify_asc_api_access() (
  local key_id="$1" issuer_id="$2" key_path="$3"
  local apple_id token response_file header_file http_status
  require_command curl "Install curl (included with macOS)."
  assert_repo_exists
  apple_id="$(cd "$APP" && app_store_connect_id)" || \
    die "eas.json does not contain a numeric submit.$PROFILE.ios.ascAppId."
  response_file="$(mktemp -t trotter-asc-response)"
  header_file="$(mktemp -t trotter-asc-header)"
  chmod 600 "$response_file" "$header_file"
  trap 'rm -f "$response_file" "$header_file"' EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  trap 'exit 129' HUP

  if ! token="$(/usr/bin/xcrun altool \
    --generate-jwt \
    --apiKey "$key_id" \
    --apiIssuer "$issuer_id" \
    --p8-file-path "$key_path" 2>&1 | \
    tr -d '\r' | \
    awk '/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/ { print; exit }')"; then
    die "Apple's uploader could not generate an authentication token from the App Store Connect key."
  fi
  if [[ ! "$token" =~ ^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$ ]]; then
    die "Apple's uploader could not generate an authentication token from the App Store Connect key."
  fi
  printf 'Authorization: Bearer %s\n' "$token" > "$header_file"
  token=""

  http_status="$(/usr/bin/curl -sS \
    --connect-timeout 15 \
    --max-time 45 \
    -o "$response_file" \
    -w '%{http_code}' \
    -H "@$header_file" \
    -H 'Accept: application/json' \
    "https://api.appstoreconnect.apple.com/v1/apps/$apple_id")" || {
      die "Could not reach the App Store Connect API."
    }
  if [[ "$http_status" != "200" ]]; then
    node - "$response_file" <<'NODE' >&2 || true
const fs = require('node:fs');
try {
  const body = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const error = Array.isArray(body.errors) ? body.errors[0] : null;
  if (error) console.error(`${error.code ?? 'APPLE_ERROR'}: ${error.detail ?? error.title ?? 'Apple rejected the request.'}`);
} catch {}
NODE
    die "App Store Connect API authentication or access to Apple app $apple_id failed (HTTP $http_status)."
  fi
  if ! node - "$response_file" "$apple_id" <<'NODE'
const fs = require('node:fs');
const body = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
if (String(body?.data?.id) !== process.argv[3]) process.exit(1);
if (body?.data?.attributes?.bundleId !== 'com.trotter.mobilev2') process.exit(1);
NODE
  then
    die "The App Store Connect key did not resolve Trotter app $apple_id with bundle ID com.trotter.mobilev2."
  fi
)

doctor_direct_submit() {
  local failed=0
  say "Direct-to-Apple upload requirements"

  if /usr/bin/xcrun --find altool >/dev/null 2>&1; then
    printf '%-20s %s\n' "Apple altool" "$(/usr/bin/xcrun --find altool)"
  else
    printf '%-20s MISSING (install full Xcode)\n' "Apple altool"
    failed=1
  fi

  if ! load_direct_submit_config; then
    failed=1
  else
    printf '%-20s %s\n' "ASC Key ID" "$ASC_KEY_ID"
    printf '%-20s PASS (owner-only files)\n' "Key permissions"
  fi

  [[ "$failed" -eq 0 ]] || \
    die "Direct-submit setup is incomplete. Run configure-direct-submit from the PC."

  verify_asc_api_access "$ASC_KEY_ID" "$ASC_ISSUER_ID" "$ASC_KEY_PATH"
  printf '%-20s PASS (Trotter app access)\n' "Apple authentication"
}

assert_direct_submit_local_install() {
  load_direct_submit_config
  printf '%-20s %s\n' "ASC Key ID" "$ASC_KEY_ID"
  printf '%-20s PASS (owner-only files)\n' "Key permissions"
}

configure_direct_submit() {
  validate_asc_key_id "$ASC_KEY_ID_INPUT" || \
    die "The App Store Connect Key ID must be exactly 10 uppercase letters or digits."
  validate_asc_issuer_id "$ASC_ISSUER_ID_INPUT" || \
    die "The App Store Connect Issuer ID must be a UUID."
  [[ "$ASC_STAGING_NAME_INPUT" =~ ^AuthKey_${ASC_KEY_ID_INPUT}\.[0-9a-f]{32}\.p8$ ]] || \
    die "The staged App Store Connect key name is invalid. Run configure-direct-submit from the PC."

  local incoming key_directory target config_temporary size old_pid cleanup_command
  incoming="$HOME/.trotter-ios-remote/incoming/$ASC_STAGING_NAME_INPUT"
  key_directory="$HOME/.appstoreconnect/private_keys"
  target="$key_directory/AuthKey_$ASC_KEY_ID_INPUT.p8"

  umask 077
  mkdir -p "$HOME/.trotter-ios-remote" "$key_directory"
  chmod 700 "$HOME/.trotter-ios-remote" "$HOME/.appstoreconnect" "$key_directory"
  if ! mkdir "$DIRECT_CONFIG_LOCK" 2>/dev/null; then
    old_pid=""
    [[ -f "$DIRECT_CONFIG_LOCK/pid" ]] && old_pid="$(cat "$DIRECT_CONFIG_LOCK/pid")"
    if [[ -n "$old_pid" ]] && ! kill -0 "$old_pid" 2>/dev/null; then
      rm -rf "$DIRECT_CONFIG_LOCK"
      mkdir "$DIRECT_CONFIG_LOCK"
    else
      die "Another direct-submit configuration appears to be running (PID ${old_pid:-unknown})."
    fi
  fi
  printf '%s\n' "$$" > "$DIRECT_CONFIG_LOCK/pid"
  config_temporary="$(mktemp "$HOME/.trotter-ios-remote/app-store-connect.conf.XXXXXX")"
  printf -v cleanup_command 'rm -f %q %q; rm -rf %q' \
    "$incoming" "$config_temporary" "$DIRECT_CONFIG_LOCK"
  trap "$cleanup_command" EXIT
  trap "$cleanup_command; exit 130" INT
  trap "$cleanup_command; exit 143" TERM
  trap "$cleanup_command; exit 129" HUP
  [[ -f "$incoming" && ! -L "$incoming" ]] || \
    die "Incoming App Store Connect key is missing or is not a regular file: $incoming"
  [[ "$(stat -f '%Su' "$incoming")" == "$(id -un)" ]] || \
    die "Incoming App Store Connect key is not owned by $(id -un)."
  chmod 600 "$incoming"
  assert_private_file "$incoming" "Incoming App Store Connect private key"
  size="$(stat -f '%z' "$incoming")"
  (( size >= 100 && size <= 16384 )) || die "Incoming App Store Connect key has an unexpected size."
  grep -qx -- '-----BEGIN PRIVATE KEY-----' "$incoming" || die "Incoming key has an invalid PKCS#8 header."
  grep -qx -- '-----END PRIVATE KEY-----' "$incoming" || die "Incoming key has an invalid PKCS#8 footer."
  /usr/bin/openssl pkey -in "$incoming" -noout >/dev/null 2>&1 || \
    die "Incoming App Store Connect private key could not be parsed."

  verify_asc_api_access "$ASC_KEY_ID_INPUT" "$ASC_ISSUER_ID_INPUT" "$incoming"

  if [[ -L "$target" ]]; then
    die "Refusing to replace a symlink at the key path: $target"
  fi
  if [[ -e "$target" && ! -f "$target" ]]; then
    die "Refusing to replace non-file key path: $target"
  fi
  if [[ -f "$target" ]] && ! cmp -s "$incoming" "$target"; then
    die "A different private key already exists for Key ID $ASC_KEY_ID_INPUT. Revoke or resolve it manually."
  fi

  [[ ! -L "$DIRECT_SUBMIT_CONFIG" ]] || \
    die "Refusing to replace a symlink at the direct-submit configuration path."
  mv -f "$incoming" "$target"
  chmod 600 "$target"
  printf 'ASC_KEY_ID=%s\nASC_ISSUER_ID=%s\n' \
    "$ASC_KEY_ID_INPUT" "$ASC_ISSUER_ID_INPUT" > "$config_temporary"
  chmod 600 "$config_temporary"
  mv -f "$config_temporary" "$DIRECT_SUBMIT_CONFIG"

  assert_direct_submit_local_install
  printf '\nDirect-to-Apple submission is configured for Key ID %s.\n' "$ASC_KEY_ID_INPUT"
}

assert_direct_submit_profile() {
  [[ "$PROFILE" == "iphone-testflight" ]] || \
    die "Direct App Store upload requires -Profile iphone-testflight, not $PROFILE."
}

latest_production_ipa() {
  local short latest="" latest_mtime=0 file file_mtime
  short="${EXPECTED_COMMIT:0:12}"
  shopt -s nullglob
  for file in "$ARTIFACTS"/trotter-ios-"$PROFILE"-"$short"-*.ipa; do
    file_mtime="$(stat -f '%m' "$file")"
    if (( file_mtime > latest_mtime )); then
      latest="$file"
      latest_mtime="$file_mtime"
    fi
  done
  shopt -u nullglob
  [[ -n "$latest" ]] || return 1
  printf '%s\n' "$latest"
}

verification_value() {
  local output="$1" key="$2"
  awk -F= -v wanted="$key" '$1 == wanted { count += 1; value = substr($0, index($0, "=") + 1) } END { if (count != 1) exit 1; print value }' <<<"$output"
}

app_store_connect_id() {
  node - "$PROFILE" <<'NODE'
const fs = require('node:fs');
const profile = process.argv[2];
const config = JSON.parse(fs.readFileSync('eas.json', 'utf8'));
const value = config?.submit?.[profile]?.ios?.ascAppId;
if (!/^\d+$/.test(String(value ?? ''))) process.exit(1);
process.stdout.write(String(value));
NODE
}

acquire_direct_submit_lock() {
  if mkdir "$DIRECT_SUBMIT_LOCK" 2>/dev/null; then
    printf '%s\n' "$$" > "$DIRECT_SUBMIT_LOCK/pid"
    trap 'rm -rf "$HOME/.trotter-ios-remote/direct-submit.lock"' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    trap 'exit 129' HUP
    return
  fi

  local old_pid=""
  [[ -f "$DIRECT_SUBMIT_LOCK/pid" ]] && old_pid="$(cat "$DIRECT_SUBMIT_LOCK/pid")"
  if [[ -n "$old_pid" ]] && ! kill -0 "$old_pid" 2>/dev/null; then
    rm -rf "$DIRECT_SUBMIT_LOCK"
    mkdir "$DIRECT_SUBMIT_LOCK"
    printf '%s\n' "$$" > "$DIRECT_SUBMIT_LOCK/pid"
    trap 'rm -rf "$HOME/.trotter-ios-remote/direct-submit.lock"' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    trap 'exit 129' HUP
    return
  fi
  die "Another direct Apple upload appears to be running (PID ${old_pid:-unknown})."
}

write_direct_submit_result() {
  local state="$1" status="$2" ipa="$3" sha="$4" apple_id="$5" version="$6" build="$7" log="$8"
  local delivery_id="${9:-}"
  local temporary="$DIRECT_SUBMIT_RESULT.$$" receipt receipt_temporary build_receipt build_temporary
  if [[ -n "$delivery_id" && ! "$delivery_id" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]; then
    die "Refusing to record an invalid Apple Delivery UUID."
  fi
  umask 077
  mkdir -p "$DIRECT_SUBMIT_RECEIPTS" "$DIRECT_SUBMIT_BUILDS"
  chmod 700 "$DIRECT_SUBMIT_RECEIPTS" "$DIRECT_SUBMIT_BUILDS"
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$state" "$status" "$EXPECTED_COMMIT" "$PROFILE" "$ipa" "$sha" "$apple_id" "$version" "$build" "$log" "$delivery_id" \
    > "$temporary"
  chmod 600 "$temporary"

  receipt="$DIRECT_SUBMIT_RECEIPTS/$sha.result"
  receipt_temporary="$receipt.$$"
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$state" "$status" "$EXPECTED_COMMIT" "$PROFILE" "$ipa" "$sha" "$apple_id" "$version" "$build" "$log" "$delivery_id" \
    > "$receipt_temporary"
  chmod 600 "$receipt_temporary"
  mv -f "$receipt_temporary" "$receipt"

  build_receipt="$DIRECT_SUBMIT_BUILDS/$apple_id-$version-$build.result"
  build_temporary="$build_receipt.$$"
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$state" "$status" "$EXPECTED_COMMIT" "$PROFILE" "$ipa" "$sha" "$apple_id" "$version" "$build" "$log" "$delivery_id" \
    > "$build_temporary"
  chmod 600 "$build_temporary"
  mv -f "$build_temporary" "$build_receipt"
  mv -f "$temporary" "$DIRECT_SUBMIT_RESULT"
}

delivery_id_from_log() {
  local source="$1" delivery_id
  [[ -f "$source" ]] || return 1
  delivery_id="$(LC_ALL=C sed -nE \
    's/.*Delivery UUID:[[:space:]]*([[:xdigit:]]{8}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{12}).*/\1/p' \
    "$source" | head -n 1 | tr '[:upper:]' '[:lower:]')"
  [[ "$delivery_id" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]] || return 1
  printf '%s\n' "$delivery_id"
}

mark_direct_submit_unknown() {
  local status="$1" delivery_id=""
  [[ -n "${latest:-}" && -n "${ipa_sha:-}" && -n "${apple_id:-}" && -n "${version:-}" && -n "${build:-}" && -n "${log:-}" ]] || return 0
  delivery_id="$(delivery_id_from_log "$log" 2>/dev/null || true)"
  write_direct_submit_result "DELIVERY_UNKNOWN" "$status" "$latest" "$ipa_sha" "$apple_id" "$version" "$build" "$log" "$delivery_id"
}

submit_local_direct() {
  assert_repo_clean_at_commit
  assert_direct_submit_profile
  doctor_direct_submit
  acquire_direct_submit_lock
  cd "$APP"

  local latest="" verification_output ipa_sha="" version="" build="" apple_id="" prior_state receipt build_receipt
  local stamp short log validation_log confirmation validation_status upload_status log_status delivery_id=""
  local -a pipeline_status
  latest="$(latest_production_ipa)" || \
    die "No Mac-local IPA matches commit $EXPECTED_COMMIT and profile $PROFILE."
  [[ -x "$IPA_VERIFY_HELPER" ]] || \
    die "IPA verifier is missing at $IPA_VERIFY_HELPER. Refresh the Mac helper and retry."

  say "Verifying exact production IPA before direct Apple upload"
  verification_output="$("$IPA_VERIFY_HELPER" "$latest" "$APP" "$PROFILE")"
  printf '%s\n' "$verification_output"
  ipa_sha="$(verification_value "$verification_output" ipa_sha256)" || die "IPA verifier omitted its SHA-256."
  version="$(verification_value "$verification_output" version)" || die "IPA verifier omitted the app version."
  build="$(verification_value "$verification_output" build)" || die "IPA verifier omitted the build number."
  apple_id="$(app_store_connect_id)" || die "eas.json does not contain a numeric submit.$PROFILE.ios.ascAppId."
  [[ "$ipa_sha" =~ ^[0-9a-f]{64}$ ]] || die "IPA verifier returned an invalid SHA-256."
  [[ "$build" =~ ^[0-9]+$ ]] || die "IPA verifier returned an invalid build number."
  [[ "$version" =~ ^[0-9A-Za-z._-]+$ ]] || die "IPA verifier returned an invalid app version."

  receipt="$DIRECT_SUBMIT_RECEIPTS/$ipa_sha.result"
  if [[ -f "$receipt" ]]; then
    IFS=$'\t' read -r prior_state _ < "$receipt" || true
    die "This exact IPA is already recorded as $prior_state. Refusing a duplicate upload. Use a new build number after resolving any failure."
  fi
  build_receipt="$DIRECT_SUBMIT_BUILDS/$apple_id-$version-$build.result"
  if [[ -f "$build_receipt" ]]; then
    IFS=$'\t' read -r prior_state _ < "$build_receipt" || true
    die "App $apple_id version $version build $build is already recorded as $prior_state. Refusing a duplicate build-number upload."
  fi

  short="${EXPECTED_COMMIT:0:12}"
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  validation_log="$ARTIFACTS/apple-validate-$PROFILE-$short-$stamp.log"
  mkdir -p "$ARTIFACTS"
  say "Validating the IPA with Apple before upload confirmation"
  printf 'This contacts App Store Connect for validation only; it does not upload the build.\nLog: %s\n' "$validation_log"
  set +e
  caffeinate -i /usr/bin/xcrun altool \
    --api-key "$ASC_KEY_ID" \
    --api-issuer "$ASC_ISSUER_ID" \
    --p8-file-path "$ASC_KEY_PATH" \
    --validate-app "$latest" \
    --output-format normal \
    --show-progress 2>&1 | tee "$validation_log"
  pipeline_status=("${PIPESTATUS[@]}")
  validation_status="${pipeline_status[0]}"
  log_status="${pipeline_status[1]}"
  set -e
  if [[ "$validation_status" -ne 0 ]]; then
    die "Apple validation failed with exit code $validation_status. Nothing was uploaded. See $validation_log"
  fi
  if [[ "$log_status" -ne 0 ]]; then
    die "Apple validation succeeded, but its local log failed with exit code $log_status. Nothing was uploaded. See $validation_log"
  fi
  [[ "$(shasum -a 256 "$latest" | awk '{print $1}')" == "$ipa_sha" ]] || \
    die "The IPA changed during Apple validation. Nothing was uploaded."

  printf '\nDirect Apple upload candidate:\n'
  printf '  IPA:       %s\n  SHA-256:   %s\n  App:       %s (%s)\n  Version:   %s (%s)\n' \
    "$latest" "$ipa_sha" "$apple_id" "com.trotter.mobilev2" "$version" "$build"
  printf 'Confirm that no EAS or Apple upload for this build is still queued.\n'
  printf 'Type UPLOAD %s to send this IPA directly to Apple, then press Enter.\n' "$build"
  confirmation=""
  IFS= read -r confirmation || true
  if [[ "$confirmation" != "UPLOAD $build" ]]; then
    printf '\nDirect upload canceled; nothing was sent.\n'
    printf 'To try again, rerun submit-local and type exactly: UPLOAD %s\n' "$build"
    return 0
  fi
  [[ "$(shasum -a 256 "$latest" | awk '{print $1}')" == "$ipa_sha" ]] || \
    die "The IPA changed while awaiting confirmation. Nothing was uploaded."

  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  log="$ARTIFACTS/apple-direct-$PROFILE-$short-$stamp.log"
  write_direct_submit_result "UPLOADING" 0 "$latest" "$ipa_sha" "$apple_id" "$version" "$build" "$log"
  trap 'mark_direct_submit_unknown 130; exit 130' INT
  trap 'mark_direct_submit_unknown 143; exit 143' TERM
  trap 'mark_direct_submit_unknown 129; exit 129' HUP

  say "Uploading directly to Apple App Store Connect"
  printf 'Apple will continue processing after this command returns.\nLog: %s\n' "$log"
  set +e
  caffeinate -i /usr/bin/xcrun altool \
    --api-key "$ASC_KEY_ID" \
    --api-issuer "$ASC_ISSUER_ID" \
    --p8-file-path "$ASC_KEY_PATH" \
    --upload-package "$latest" \
    --output-format normal \
    --show-progress 2>&1 | tee "$log"
  pipeline_status=("${PIPESTATUS[@]}")
  upload_status="${pipeline_status[0]}"
  log_status="${pipeline_status[1]}"
  set -e
  delivery_id="$(delivery_id_from_log "$log" 2>/dev/null || true)"
  if [[ "$upload_status" -ne 0 ]]; then
    write_direct_submit_result "DELIVERY_UNKNOWN" "$upload_status" "$latest" "$ipa_sha" "$apple_id" "$version" "$build" "$log" "$delivery_id"
    die "Apple upload returned exit code $upload_status. Do not retry this build number until App Store Connect confirms it was not received. See $log"
  fi
  if [[ "$log_status" -ne 0 ]]; then
    write_direct_submit_result "DELIVERY_UNKNOWN" "$log_status" "$latest" "$ipa_sha" "$apple_id" "$version" "$build" "$log" "$delivery_id"
    die "Apple returned success, but the local log failed with exit code $log_status. Treat delivery as potentially successful and check App Store Connect before doing anything else."
  fi

  write_direct_submit_result "DELIVERED" 0 "$latest" "$ipa_sha" "$apple_id" "$version" "$build" "$log" "$delivery_id"
  printf '\nApple accepted the direct upload for delivery. TestFlight processing may continue.\n'
  if [[ -n "$delivery_id" ]]; then
    printf 'Delivery UUID: %s\n' "$delivery_id"
  else
    printf 'Apple did not include a Delivery UUID in the uploader output; use App Store Connect for status.\n'
  fi
  printf 'Check it with: .\\.ios-remote\\trotter-ios.ps1 direct-submit-status\n'
}

direct_submit_status() {
  if [[ ! -f "$DIRECT_SUBMIT_RESULT" ]]; then
    printf '\nNo direct Apple upload has been recorded yet.\n'
    printf 'App Store Connect: https://appstoreconnect.apple.com/apps\n'
    return 0
  fi
  doctor_direct_submit

  local state status commit profile ipa sha apple_id version build log delivery_id=""
  IFS=$'\t' read -r state status commit profile ipa sha apple_id version build log delivery_id < "$DIRECT_SUBMIT_RESULT"
  printf '\n==> Last direct Apple upload\n'
  printf 'State:    %s\nCommit:   %s\nProfile:  %s\nIPA:      %s\nSHA-256:  %s\nVersion:  %s (%s)\nLog:      %s\n' \
    "$state" "$commit" "$profile" "$ipa" "$sha" "$version" "$build" "$log"
  if [[ -n "$delivery_id" ]]; then
    printf 'Delivery: %s\n' "$delivery_id"
  fi
  if [[ "$state" != "DELIVERED" ]]; then
    printf 'The local result is %s; Apple status is authoritative before any retry.\n' "$state" >&2
  fi
  if [[ -z "$delivery_id" ]]; then
    printf 'This receipt predates Delivery UUID tracking, or Apple did not return one.\n'
    printf 'Check this build in App Store Connect: https://appstoreconnect.apple.com/apps/%s/testflight/ios\n' "$apple_id"
    return 0
  fi
  printf 'A newly delivered build may take a few minutes to appear; retry this status check if Apple reports that it cannot be found yet.\n'

  say "Apple processing status"
  direct_delivery_status "$delivery_id" "$version" "$build"
}

direct_delivery_status() (
  local delivery_id="$1" expected_version="$2" expected_build="$3"
  local token response_file header_file http_status
  response_file="$(mktemp -t trotter-asc-delivery)"
  header_file="$(mktemp -t trotter-asc-header)"
  chmod 600 "$response_file" "$header_file"
  trap 'rm -f "$response_file" "$header_file"' EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  trap 'exit 129' HUP

  if ! token="$(/usr/bin/xcrun altool \
    --generate-jwt \
    --apiKey "$ASC_KEY_ID" \
    --apiIssuer "$ASC_ISSUER_ID" \
    --p8-file-path "$ASC_KEY_PATH" 2>&1 | \
    tr -d '\r' | \
    awk '/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/ { print; exit }')"; then
    die "Apple's uploader could not generate an authentication token for the delivery-status request."
  fi
  [[ "$token" =~ ^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$ ]] || \
    die "Apple's uploader returned an invalid authentication token for the delivery-status request."
  printf 'Authorization: Bearer %s\n' "$token" > "$header_file"
  token=""

  http_status="$(/usr/bin/curl -sS \
    --connect-timeout 15 \
    --max-time 45 \
    -o "$response_file" \
    -w '%{http_code}' \
    -H "@$header_file" \
    -H 'Accept: application/json' \
    "https://api.appstoreconnect.apple.com/v1/buildUploads/$delivery_id")" || \
    die "Could not reach App Store Connect for delivery status."

  if [[ "$http_status" == "404" ]]; then
    printf 'Apple has not exposed delivery %s yet. Retry in a few minutes.\n' "$delivery_id"
    return 0
  fi
  if [[ "$http_status" != "200" ]]; then
    node - "$response_file" <<'NODE' >&2 || true
const fs = require('node:fs');
try {
  const body = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const error = Array.isArray(body.errors) ? body.errors[0] : null;
  if (error) console.error(`${error.code ?? 'APPLE_ERROR'}: ${error.detail ?? error.title ?? 'Apple rejected the request.'}`);
} catch {}
NODE
    die "App Store Connect delivery-status request failed (HTTP $http_status)."
  fi

  node - "$response_file" "$delivery_id" "$expected_version" "$expected_build" <<'NODE'
const fs = require('node:fs');
const body = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const expectedDelivery = process.argv[3];
const expectedVersion = process.argv[4];
const expectedBuild = process.argv[5];
const data = body?.data;
const attributes = data?.attributes;
if (data?.type !== 'buildUploads' || data?.id !== expectedDelivery) {
  throw new Error('Apple returned a different delivery record than requested.');
}
if (attributes?.cfBundleShortVersionString !== expectedVersion || attributes?.cfBundleVersion !== expectedBuild) {
  throw new Error('Apple delivery version/build does not match the local receipt.');
}
if (attributes?.platform !== 'IOS') throw new Error('Apple delivery platform is not iOS.');
const processing = attributes?.state ?? {};
const state = processing.state ?? 'UNKNOWN';
const errors = Array.isArray(processing.errors) ? processing.errors : [];
const warnings = Array.isArray(processing.warnings) ? processing.warnings : [];
console.log(`Delivery:  ${expectedDelivery}`);
console.log(`Version:   ${expectedVersion} (${expectedBuild})`);
console.log(`State:     ${state}`);
console.log(`Uploaded:  ${attributes.uploadedDate ?? 'not reported'}`);
console.log(`Errors:    ${errors.length}`);
console.log(`Warnings:  ${warnings.length}`);
for (const error of errors) {
  console.error(`${error.code ?? 'APPLE_ERROR'}: ${error.description ?? error.detail ?? error.title ?? 'Apple reported a processing error.'}`);
}
for (const warning of warnings) {
  console.warn(`${warning.code ?? 'APPLE_WARNING'}: ${warning.description ?? warning.detail ?? warning.title ?? 'Apple reported a processing warning.'}`);
}
if (errors.length > 0 || state === 'FAILED') process.exit(1);
NODE
)

prepare_local_build_plugin() {
  [[ "$PROFILE" != "iphone-simulator" ]] || return 0

  local plugin_package build_tools_package keychain_source
  plugin_package="$LOCAL_BUILD_PLUGIN_ROOT/node_modules/eas-cli-local-build-plugin/package.json"
  build_tools_package="$LOCAL_BUILD_PLUGIN_ROOT/node_modules/@expo/build-tools/package.json"
  keychain_source="$LOCAL_BUILD_PLUGIN_ROOT/node_modules/@expo/build-tools/dist/ios/credentials/keychain.js"

  if [[ ! -f "$plugin_package" || ! -f "$build_tools_package" || ! -f "$keychain_source" ]]; then
    say "Installing isolated EAS local-build tooling"
    [[ "$LOCAL_BUILD_PLUGIN_ROOT" == "$HOME/.trotter-ios-remote/tooling/eas-local-build-plugin-$LOCAL_BUILD_PLUGIN_VERSION" && ! -L "$LOCAL_BUILD_PLUGIN_ROOT" ]] || die "Unsafe tooling path."
    rm -rf "$LOCAL_BUILD_PLUGIN_ROOT"
    mkdir -p "$LOCAL_BUILD_PLUGIN_ROOT"
    npm install \
      --prefix "$LOCAL_BUILD_PLUGIN_ROOT" \
      --no-save \
      --package-lock=false \
      --no-audit \
      --no-fund \
      "eas-cli-local-build-plugin@$LOCAL_BUILD_PLUGIN_VERSION"
  fi

  node - "$plugin_package" "$build_tools_package" "$LOCAL_BUILD_PLUGIN_VERSION" <<'NODE'
const fs = require('node:fs');
const [pluginPath, buildToolsPath, expected] = process.argv.slice(2);
const plugin = JSON.parse(fs.readFileSync(pluginPath, 'utf8'));
const buildTools = JSON.parse(fs.readFileSync(buildToolsPath, 'utf8'));
if (plugin.version !== expected || buildTools.version !== expected) {
  throw new Error(
    `Refusing unpinned local tooling: plugin=${plugin.version}, build-tools=${buildTools.version}, expected=${expected}`
  );
}
NODE

  # Do not patch security find-identity or certificate trust. A signing failure
  # must be investigated for this project; other apps' local workarounds do not apply.
  [[ -x "$LOCAL_BUILD_PLUGIN_BIN" ]] || chmod 755 "$LOCAL_BUILD_PLUGIN_BIN"
  export EAS_LOCAL_BUILD_PLUGIN_PATH="$LOCAL_BUILD_PLUGIN_BIN"
  printf 'Using unmodified, pinned local-build plugin %s at %s\n' \
    "$LOCAL_BUILD_PLUGIN_VERSION" "$LOCAL_BUILD_PLUGIN_BIN"
}

run_expo_doctor_release_gate() {
  # Trotter uses Expo SDK 54. No advisory exception from another app applies.
  npx --yes expo-doctor@latest
}

validate_repo() {
  assert_repo_clean_at_commit
  cd "$APP"
  assert_node_version

  say "Installing exact npm dependencies"
  npm ci

  say "TypeScript"
  npm run typecheck

  say "Logic tests"
  npm run test:iphone
  node --test scripts/testEasArchive.cjs

  say "iOS native project generation"
  npm run ios:verify-prebuild

  say "iPhone release configuration"
  EAS_BUILD_PROFILE="$PROFILE" node scripts/checkIosReadiness.cjs

  say "Expo Doctor"
  run_expo_doctor_release_gate

  assert_repo_clean_at_commit
  printf '\nValidation passed for %s.\n' "$EXPECTED_COMMIT"
}

acquire_local_build_lock() {
  local lock="$HOME/.trotter-ios-remote/local-build.lock"
  [[ ! -L "$lock" ]] || die "Unsafe build lock."
  if pgrep -x xcodebuild >/dev/null; then die "Another Xcode build is active on this Mac. Retry after it finishes."; fi
  if mkdir "$lock" 2>/dev/null; then
    printf '%s\n' "$$" > "$lock/pid"
    trap 'rm -rf "$HOME/.trotter-ios-remote/local-build.lock"' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    return
  fi

  local old_pid=""
  [[ -f "$lock/pid" ]] && old_pid="$(cat "$lock/pid")"
  if [[ "$old_pid" =~ ^[0-9]+$ ]] && ! kill -0 "$old_pid" 2>/dev/null; then
    rm -rf "$lock"
    mkdir "$lock"
    printf '%s\n' "$$" > "$lock/pid"
    trap 'rm -rf "$HOME/.trotter-ios-remote/local-build.lock"' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    return
  fi

  die "Another Mac-local iOS build appears to be running (PID ${old_pid:-unknown})."
}

write_local_build_result() {
  local state="$1" status="$2" output="${3:-}" log="${4:-}"
  local temporary="$LOCAL_BUILD_RESULT.$$"
  mkdir -p "$(dirname "$LOCAL_BUILD_RESULT")"
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$state" "$status" "$EXPECTED_COMMIT" "$PROFILE" "$output" "$log" > "$temporary"
  mv "$temporary" "$LOCAL_BUILD_RESULT"
}

report_local_build_result() {
  local state status commit profile output log
  if [[ ! -f "$LOCAL_BUILD_RESULT" ]]; then
    if tmux has-session -t "$LOCAL_BUILD_SESSION" 2>/dev/null; then
      printf '\nThe Mac-local build is still running in tmux. Use the attach action to reconnect.\n'
      return 0
    fi
    die "The local build session ended without writing a result. Inspect the newest log in $ARTIFACTS."
  fi

  IFS=$'\t' read -r state status commit profile output log < "$LOCAL_BUILD_RESULT"
  [[ "$commit" == "$EXPECTED_COMMIT" && "$profile" == "$PROFILE" ]] || \
    die "The saved local-build result belongs to $commit ($profile), not $EXPECTED_COMMIT ($PROFILE)."

  printf '\n==> Mac-local build result\n'
  printf 'Status:   %s\nCommit:   %s\nProfile:  %s\n' "$state" "$commit" "$profile"
  [[ -n "$output" ]] && printf 'Artifact: %s\n' "$output"
  [[ -n "$log" ]] && printf 'Log:      %s\n' "$log"

  if [[ "$state" == "SUCCEEDED" && -s "$output" ]]; then
    return 0
  fi
  if [[ "$state" == "RUNNING" ]]; then
    if tmux has-session -t "$LOCAL_BUILD_SESSION" 2>/dev/null; then
      printf 'The build is still running. Use the attach action to reconnect.\n'
      return 0
    fi
    printf 'The build worker stopped before recording a final result. Inspect the log above.\n' >&2
    return 70
  fi
  [[ "$status" =~ ^[1-9][0-9]*$ && "$status" -le 255 ]] || status=1
  return "$status"
}

run_local_build() {
  assert_repo_clean_at_commit
  doctor_local
  acquire_local_build_lock
  prepare_local_build_plugin
  mkdir -p "$ARTIFACTS"
  cd "$APP"
  EAS_BUILD_PROFILE="$PROFILE" node scripts/checkIosReadiness.cjs

  local short stamp extension output log
  short="${EXPECTED_COMMIT:0:12}"
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  extension="ipa"
  if [[ "$PROFILE" == "iphone-simulator" ]]; then
    extension="tar.gz"
  fi
  output="$ARTIFACTS/trotter-ios-$PROFILE-$short-$stamp.$extension"
  log="$ARTIFACTS/trotter-ios-$PROFILE-$short-$stamp.log"
  write_local_build_result "RUNNING" 0 "$output" "$log"

  say "Mac-local EAS build"
  printf 'Commit:  %s\nProfile: %s\nOutput:  %s\nLog:     %s\n' \
    "$EXPECTED_COMMIT" "$PROFILE" "$output" "$log"

  set +e
  caffeinate -i nice -n 10 npx --yes "eas-cli@$EAS_VERSION" build \
    --platform ios \
    --profile "$PROFILE" \
    --local \
    --non-interactive \
    --output "$output" \
    --message "ios local $PROFILE $short" 2>&1 | tee "$log"
  local build_status="${PIPESTATUS[0]}"
  set -e
  if [[ "$build_status" -ne 0 ]]; then
    write_local_build_result "FAILED" "$build_status" "$output" "$log"
    die "Local build failed with exit code $build_status. See $log"
  fi

  [[ -s "$output" ]] || {
    write_local_build_result "FAILED" 1 "$output" "$log"
    die "Local build reported success but did not create $output"
  }
  write_local_build_result "SUCCEEDED" 0 "$output" "$log"

  printf '\nLocal build completed: %s\n' "$output"
}

snapshot_result() {
  local result="$HOME/.trotter-ios-remote/snapshot-$EXPECTED_COMMIT.result" id state artifact sha
  [[ -f "$result" && ! -L "$result" ]] || die "No result exists for snapshot $EXPECTED_COMMIT yet."
  id="$(verification_value "$(cat "$result")" content_id)"
  [[ "$id" == "$EXPECTED_COMMIT" ]] || die "Snapshot result identity mismatch."
  state="$(verification_value "$(cat "$result")" state)"
  if [[ "$ACTION" == snapshot-latest-artifact ]]; then
    [[ "$state" == SUCCEEDED ]] || die "Snapshot has not succeeded: $state"
    artifact="$(verification_value "$(cat "$result")" artifact)"
    sha="$(verification_value "$(cat "$result")" artifact_sha256)"
    [[ "$artifact" == "$ARTIFACTS/trotter-ios-snapshot-$EXPECTED_COMMIT-"*.tar.gz && -s "$artifact" && ! -L "$artifact" && "$sha" =~ ^[a-f0-9]{64}$ ]] || die "Invalid snapshot artifact."
    [[ "$(shasum -a 256 "$artifact" | awk '{print $1}')" == "$sha" ]] || die "Snapshot artifact checksum mismatch."
    printf '%s\n' "$artifact"
  else
    cat "$result"
    if [[ "$state" == RUNNING ]] && ! tmux has-session -t trotter-ios-snapshot 2>/dev/null; then
      die "The snapshot worker stopped without recording a final result. Inspect its log."
    fi
    [[ "$state" != FAILED ]]
  fi
}

assert_trotter_paths
load_build_environment
case "$ACTION" in
  simulator-snapshot)
    require_command tmux "Install tmux to keep snapshot compilation running after SSH disconnects."
    [[ "$ASC_KEY_ID_INPUT" =~ ^[a-f0-9]{64}$ ]] || die "Snapshot archive SHA-256 is required as argument 9."
    [[ -x "$HOME/.trotter-ios-remote/snapshot-build.sh" ]] || die "Snapshot build helper is missing."
    if tmux has-session -t trotter-ios-snapshot 2>/dev/null; then die "A Trotter simulator snapshot build is already running. Use snapshot-status."; fi
    printf -v snapshot_command '%q ' /usr/bin/caffeinate -i "$HOME/.trotter-ios-remote/snapshot-build.sh" \
      "$HOME/.trotter-ios-remote/incoming/$EXPECTED_COMMIT.tar.gz" "$ASC_KEY_ID_INPUT" "$EXPECTED_COMMIT" "$ARTIFACTS"
    tmux new-session -d -s trotter-ios-snapshot "$snapshot_command"
    printf 'Started simulator build for snapshot %s. Use snapshot-status to inspect its log and final result.\n' "$EXPECTED_COMMIT"
    ;;
  snapshot-status|snapshot-latest-artifact)
    snapshot_result
    ;;
  setup)
    require_command git "Install the Xcode Command Line Tools."
    require_command node "Install Node 22."
    require_command npm "Install Node 22."
    if [[ ! -d "$REPO/.git" ]]; then
      say "Cloning dedicated build repository"
      mkdir -p "$(dirname "$REPO")"
      git clone --branch "$BRANCH" --single-branch "$REPO_URL" "$REPO"
    fi
    sync_exact_commit
    cd "$APP"
    npm ci
    printf '\nSetup complete at %s\n' "$REPO"
    ;;
  sync)
    sync_exact_commit
    ;;
  doctor)
    doctor_cloud
    ;;
  doctor-local)
    doctor_local
    ;;
  configure-direct-submit)
    configure_direct_submit
    ;;
  doctor-direct-submit)
    doctor_direct_submit
    ;;
  validate)
    validate_repo
    ;;
  eas-login)
    require_command node "Install Node 22."
    require_command npx "Install Node 22."
    eas login --no-browser
    ;;
  credentials)
    assert_repo_clean_at_commit
    cd "$APP"
    # SSH sessions cannot interact with the macOS login Keychain reliably. EAS
    # officially supports disabling its local password cache; the password is
    # then used only for this interactive credentials run and is not persisted.
    export EXPO_NO_KEYCHAIN=1
    exec caffeinate -i npx --yes "eas-cli@$EAS_VERSION" credentials --platform ios
    ;;
  build-cloud)
    assert_repo_clean_at_commit
    cd "$APP"
    short="${EXPECTED_COMMIT:0:12}"
    exec caffeinate -i npx --yes "eas-cli@$EAS_VERSION" build \
      --platform ios \
      --profile "$PROFILE" \
      --message "ios cloud $PROFILE $short" \
      --no-wait
    ;;
  build-local)
    assert_repo_clean_at_commit
    if command -v tmux >/dev/null 2>&1; then
      if tmux has-session -t "$LOCAL_BUILD_SESSION" 2>/dev/null; then
        tmux attach-session -t "$LOCAL_BUILD_SESSION" || true
      else
        rm -f "$LOCAL_BUILD_RESULT"
        printf -v tmux_command '%q ' "$SELF" local-run "$REPO_INPUT" "$REPO_URL" "$BRANCH" "$EXPECTED_COMMIT" "$PROFILE" "$ARTIFACTS_INPUT" "$EAS_VERSION"
        tmux new-session -s "$LOCAL_BUILD_SESSION" "$tmux_command" || true
      fi
      report_local_build_result
      exit $?
    fi
    printf 'tmux is unavailable; the build will stop if this SSH session disconnects.\n' >&2
    rm -f "$LOCAL_BUILD_RESULT"
    "$SELF" local-run "$REPO_INPUT" "$REPO_URL" "$BRANCH" "$EXPECTED_COMMIT" "$PROFILE" "$ARTIFACTS_INPUT" "$EAS_VERSION" || true
    report_local_build_result
    ;;
  local-run)
    set +e
    (set -e; run_local_build)
    local_status=$?
    set -e
    if [[ "$local_status" -ne 0 ]]; then
      if [[ ! -f "$LOCAL_BUILD_RESULT" ]] || grep -q $'^RUNNING\t' "$LOCAL_BUILD_RESULT"; then
        write_local_build_result "FAILED" "$local_status"
      fi
    fi
    exit "$local_status"
    ;;
  attach)
    require_command tmux "Install tmux with Homebrew for persistent local builds."
    if tmux has-session -t "$LOCAL_BUILD_SESSION" 2>/dev/null; then
      tmux attach-session -t "$LOCAL_BUILD_SESSION" || true
    fi
    report_local_build_result
    ;;
  status)
    assert_repo_exists
    cd "$APP"
    exec npx --yes "eas-cli@$EAS_VERSION" build:list --platform ios --limit 5
    ;;
  submit-latest)
    assert_direct_submit_profile
    assert_repo_clean_at_commit
    cd "$APP"

    build_json="$(eas build:list \
      --platform ios \
      --status finished \
      --build-profile "$PROFILE" \
      --git-commit-hash "$EXPECTED_COMMIT" \
      --limit 1 \
      --json)"
    build_id="$(printf '%s' "$build_json" | node -e '
      const fs = require("fs");
      const builds = JSON.parse(fs.readFileSync(0, "utf8"));
      if (!Array.isArray(builds) || !builds[0]?.id) process.exit(1);
      process.stdout.write(builds[0].id);
    ')" || die "No finished iOS EAS build matches commit $EXPECTED_COMMIT and profile $PROFILE."

    printf 'Submitting EAS build %s for commit %s (%s).\n' "$build_id" "$EXPECTED_COMMIT" "$PROFILE"
    export EXPO_NO_KEYCHAIN=1
    exec caffeinate -i npx --yes "eas-cli@$EAS_VERSION" submit \
      --platform ios \
      --profile "$PROFILE" \
      --id "$build_id" \
      --no-wait
    ;;
  submit-local)
    submit_local_direct
    ;;
  submit-local-eas)
    assert_direct_submit_profile
    assert_repo_clean_at_commit
    cd "$APP"

    [[ "$PROFILE" != "iphone-simulator" ]] || \
      die "The iphone-simulator profile produces an unsigned simulator archive, not a submit-ready IPA."

    short="${EXPECTED_COMMIT:0:12}"
    latest=""
    latest_mtime=0
    shopt -s nullglob
    for file in "$ARTIFACTS"/trotter-ios-"$PROFILE"-"$short"-*.ipa; do
      file_mtime="$(stat -f '%m' "$file")"
      if (( file_mtime > latest_mtime )); then
        latest="$file"
        latest_mtime="$file_mtime"
      fi
    done
    shopt -u nullglob
    [[ -n "$latest" ]] || \
      die "No Mac-local IPA matches commit $EXPECTED_COMMIT and profile $PROFILE."

    [[ -x "$IPA_VERIFY_HELPER" ]] || \
      die "IPA verifier is missing at $IPA_VERIFY_HELPER. Refresh the Mac helper and retry."
    say "Verifying exact production IPA before upload"
    "$IPA_VERIFY_HELPER" "$latest" "$APP" "$PROFILE"

    printf 'Submitting local IPA %s for commit %s (%s).\n' "$latest" "$EXPECTED_COMMIT" "$PROFILE"
    export EXPO_NO_KEYCHAIN=1
    exec caffeinate -i npx --yes "eas-cli@$EAS_VERSION" submit \
      --platform ios \
      --profile "$PROFILE" \
      --path "$latest"
    ;;
  direct-submit-status)
    direct_submit_status
    ;;
  latest-artifact)
    short="${EXPECTED_COMMIT:0:12}"
    latest=""
    latest_mtime=0
    shopt -s nullglob
    for file in "$ARTIFACTS"/trotter-ios-"$PROFILE"-"$short"-*.ipa \
      "$ARTIFACTS"/trotter-ios-"$PROFILE"-"$short"-*.tar.gz; do
      file_mtime="$(stat -f '%m' "$file")"
      if (( file_mtime > latest_mtime )); then
        latest="$file"
        latest_mtime="$file_mtime"
      fi
    done
    shopt -u nullglob
    [[ -n "$latest" ]] || exit 1
    printf '%s\n' "$latest"
    ;;
  *)
    die "Unknown action: $ACTION"
    ;;
esac
