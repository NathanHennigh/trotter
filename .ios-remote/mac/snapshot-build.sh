#!/usr/bin/env bash
# Compile the current source snapshot without Apple distribution credentials.
set -Eeuo pipefail
umask 077
export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8
export PATH="/opt/homebrew/opt/node@22/bin:/usr/local/opt/node@22/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
ARCHIVE="${1:?snapshot archive required}"
ARCHIVE_SHA="${2:?archive SHA-256 required}"
CONTENT_ID="${3:?content ID required}"
ARTIFACTS="${4:?artifact directory required}"
ROOT="$HOME/.trotter-ios-remote"
RESULT="$ROOT/snapshot-$CONTENT_ID.result"
LOCK="$ROOT/local-build.lock"
SESSION="trotter-ios-snapshot"
OUTPUT="" LOG="" WORK="" LOCK_HELD=0

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[[ "$CONTENT_ID" =~ ^[a-f0-9]{64}$ && "$ARCHIVE_SHA" =~ ^[a-f0-9]{64}$ ]] || fail 'Invalid snapshot identity.'
[[ "$ARCHIVE" == "$ROOT/incoming/$CONTENT_ID.tar.gz" && -f "$ARCHIVE" && ! -L "$ARCHIVE" ]] || fail 'Unexpected snapshot archive path.'
[[ "$ARTIFACTS" == "$HOME/TrotterBuilds" && ! -L "$ARTIFACTS" && ! -L "$ROOT" ]] || fail 'Unexpected Trotter output directory.'
[[ ! -L "$ROOT/snapshots" && ! -L "$ROOT/snapshots/$CONTENT_ID" ]] || fail 'Snapshot parent directories cannot be symlinks.'
[[ "$(shasum -a 256 "$ARCHIVE" | awk '{print $1}')" == "$ARCHIVE_SHA" ]] || fail 'Snapshot archive checksum mismatch.'
mkdir -p "$ROOT" "$ARTIFACTS"
chmod 700 "$ROOT" "$ARTIFACTS"

write_result() {
  local state="$1" status="$2" sha=""
  if [[ "$state" == SUCCEEDED ]]; then sha="$(shasum -a 256 "$OUTPUT" | awk '{print $1}')"; fi
  printf 'state=%s\nstatus=%s\ncontent_id=%s\nartifact=%s\nartifact_sha256=%s\nlog=%s\nwork=%s\n' \
    "$state" "$status" "$CONTENT_ID" "$OUTPUT" "$sha" "$LOG" "$WORK" > "$RESULT.$$"
  mv "$RESULT.$$" "$RESULT"
}
finish() {
  local status=$?
  trap - EXIT
  if [[ "$LOCK_HELD" == 1 ]]; then
    if [[ "$status" != 0 ]]; then write_result FAILED "$status"; fi
    if [[ "$(cat "$LOCK/pid" 2>/dev/null || true)" == "$$" ]]; then rm -f "$LOCK/pid"; rmdir "$LOCK"; fi
  fi
  exit "$status"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
if ! mkdir "$LOCK" 2>/dev/null; then
  old_pid="$(cat "$LOCK/pid" 2>/dev/null || true)"
  if [[ "$old_pid" =~ ^[0-9]+$ ]] && ! kill -0 "$old_pid" 2>/dev/null; then
    [[ ! -L "$LOCK" && -f "$LOCK/pid" && ! -L "$LOCK/pid" ]] || fail 'Unsafe existing build lock.'
    rm "$LOCK/pid"; rmdir "$LOCK"; mkdir "$LOCK"
  else
    fail "Another Trotter native build is running (PID ${old_pid:-unknown})."
  fi
fi
printf '%s\n' "$$" > "$LOCK/pid"
LOCK_HELD=1
# A snapshot never touches signing or another app's checkout/keychain. Avoid
# resource contention with other native builds on the shared Mac as well.
if pgrep -x xcodebuild >/dev/null; then fail 'Another Xcode build is active. Retry after it finishes.'; fi

stamp="$(date -u +%Y%m%dT%H%M%SZ)-$$"
WORK="$ROOT/snapshots/$CONTENT_ID/$stamp"
OUTPUT="$ARTIFACTS/trotter-ios-snapshot-$CONTENT_ID-$stamp.tar.gz"
LOG="$ARTIFACTS/trotter-ios-snapshot-$CONTENT_ID-$stamp.log"
write_result RUNNING 0
exec > >(tee -a "$LOG") 2>&1
printf 'Snapshot: %s\nLog: %s\n' "$CONTENT_ID" "$LOG"
for tool in python3 node npm xcodebuild xcrun pod swiftc; do command -v "$tool" >/dev/null || fail "Missing $tool."; done
xcodebuild -checkFirstLaunchStatus
node -e 'const [a,b,c]=process.versions.node.split(".").map(Number); if (!(a>20 || a===20 && (b>19 || b===19 && c>=4))) process.exit(1)'

# build.env is an optional owner-only KEY=value file, never executable shell.
env_file="$ROOT/build.env"
if [[ -e "$env_file" ]]; then
  [[ -f "$env_file" && ! -L "$env_file" && "$(stat -f '%Su' "$env_file")" == "$(id -un)" && "$(stat -f '%Lp' "$env_file")" == 600 ]] || fail 'build.env must be an owner-only regular file.'
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    [[ -z "$line" || "$line" == \#* ]] && continue
    key="${line%%=*}"; value="${line#*=}"
    case "$key" in EXPO_PUBLIC_TROTTER_API_URL|EXPO_PUBLIC_APPLE_SIGN_IN_ENABLED|GOOGLE_MAPS_IOS_API_KEY|APPLE_TEAM_ID|APPLE_APP_ID_PREFIX|EAS_PROJECT_ID) ;; *) fail 'Unsupported key in build.env.' ;; esac
    [[ "$line" == *=* && "$value" != \"* && "$value" != \'* ]] || fail 'Use unquoted KEY=value lines in build.env.'
    export "$key=$value"
  done < "$env_file"
fi
export EXPO_PUBLIC_TROTTER_API_URL="${EXPO_PUBLIC_TROTTER_API_URL:-https://trotter-api.thehennighs.com}"
export EXPO_NO_DOTENV=1 CI=1 RCT_NO_LAUNCH_PACKAGER=1
if [[ -z "${GOOGLE_MAPS_IOS_API_KEY:-}" ]]; then
  printf 'LIMITATION: No iOS Maps key is configured. This simulator compile exercises the safe map fallback; actual maps remain unverified.\n'
fi
printf 'LIMITATION: Simulator compilation does not verify device signing, real Instagram sharing, or Apple login.\n'
python3 "$ROOT/verify-snapshot.py" "$ARCHIVE" "$WORK" "$CONTENT_ID"
APP="$WORK/mobile-v2"
cd "$APP"
printf '\n==> Exact npm dependencies\n'
npm ci --no-audit --no-fund
printf '\n==> Swift share-inbox checks\n'
swiftc native-ios/shared/DreamShareInbox.swift native-ios/tests/main.swift -o "$WORK/inbox-tests"
"$WORK/inbox-tests"
printf '\n==> Generate iPhone app and share extension\n'
npx --no-install expo prebuild --platform ios --clean --no-install
printf '\n==> Install CocoaPods dependencies\n'
(cd ios && pod install)
shopt -s nullglob
workspaces=("$APP"/ios/*.xcworkspace)
[[ "${#workspaces[@]}" == 1 ]] || fail 'Expected exactly one generated Xcode workspace.'
printf '\n==> Compile Release simulator app with local ad hoc signing\n'
# Xcode must inject simulator entitlements for SecureStore and the shared inbox.
# Ad hoc signing requires no Apple certificate or provisioning profile; disabling
# signing entirely produces an app that launches but cannot access Keychain.
caffeinate -i nice -n 10 xcodebuild \
  -workspace "${workspaces[0]}" -scheme Trotter -configuration Release \
  -sdk iphonesimulator -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath "$WORK/DerivedData" -jobs 4 \
  ARCHS=arm64 ONLY_ACTIVE_ARCH=YES CODE_SIGNING_ALLOWED=YES CODE_SIGNING_REQUIRED=NO CODE_SIGN_IDENTITY=- build
apps=("$WORK"/DerivedData/Build/Products/Release-iphonesimulator/*.app)
[[ "${#apps[@]}" == 1 ]] || fail 'Expected exactly one compiled simulator app.'
bundle="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "${apps[0]}/Info.plist")"
[[ "$bundle" == com.trotter.mobilev2 ]] || fail 'Compiled artifact has the wrong app identity.'
[[ -d "${apps[0]}/PlugIns/TrotterShare.appex" ]] || fail 'Share extension is absent from the app.'
python3 "$ROOT/artifact-validation.py" simulator-entitlements "${apps[0]}"
tar -czf "$OUTPUT" -C "$(dirname "${apps[0]}")" "$(basename "${apps[0]}")"
[[ -s "$OUTPUT" ]] || fail 'Simulator archive was not created.'
write_result SUCCEEDED 0
printf '\nSimulator build completed: %s\n' "$OUTPUT"
