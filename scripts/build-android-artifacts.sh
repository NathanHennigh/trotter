#!/usr/bin/env bash
set -Eeuo pipefail

MODE="${1:-apk}"
SOURCE_SHA="${2:-}"
SOURCE_ROOT="${3:-}"
WINDOWS_BUILDS="${4:-}"
VERSION_CODE="${5:-0}"
BUILD_CHANNEL="${6:-release}"
API_BASE_URL="${7:-}"

case "$MODE" in
  apk|aab|both) ;;
  *)
    echo "ERROR: Expected mode 'apk', 'aab', or 'both', got: $MODE" >&2
    exit 2
    ;;
esac

case "$BUILD_CHANNEL" in
  release|development) ;;
  *)
    echo "ERROR: Expected build channel 'release' or 'development', got: $BUILD_CHANNEL" >&2
    exit 2
    ;;
esac

if [[ -n "$API_BASE_URL" && ! "$API_BASE_URL" =~ ^https?://[^/]+/?$ ]]; then
  echo 'ERROR: API base URL must be an absolute HTTP(S) origin without a path.' >&2
  exit 2
fi
if [[ "$BUILD_CHANNEL" == 'release' && ! "$API_BASE_URL" =~ ^https://[^/]+/?$ ]]; then
  echo 'ERROR: Release builds require an HTTPS API base URL.' >&2
  exit 2
fi

if [[ ! "$SOURCE_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo 'ERROR: Expected the exact 40-character lowercase Git commit SHA.' >&2
  exit 2
fi

if [[ ! -d "$SOURCE_ROOT/mobile-v2" ]]; then
  echo "ERROR: Windows source directory was not found from WSL: $SOURCE_ROOT/mobile-v2" >&2
  exit 2
fi

SOURCE_MOBILE="$SOURCE_ROOT/mobile-v2"
if [[ ! -f "$SOURCE_MOBILE/package.json" || ! -f "$SOURCE_MOBILE/android/gradlew" ]]; then
  echo "ERROR: The WSL source path is not a Trotter mobile project: $SOURCE_MOBILE" >&2
  exit 2
fi

if [[ "$WINDOWS_BUILDS" != /* ]]; then
  echo "ERROR: Expected an absolute WSL output path, got: $WINDOWS_BUILDS" >&2
  exit 2
fi

if [[ "$MODE" == 'aab' || "$MODE" == 'both' ]]; then
  if [[ ! "$VERSION_CODE" =~ ^[1-9][0-9]*$ ]]; then
    echo 'ERROR: A positive Play version code is required for an AAB.' >&2
    exit 2
  fi
  if [[ ! -f "$SOURCE_MOBILE/android/signing.properties" ]]; then
    echo 'ERROR: android/signing.properties is required for an AAB.' >&2
    exit 2
  fi
fi

PROJECT="$HOME/projects/trotter-mobile-v2"
NVM_NODE_VERSION="20.20.2"

echo
echo '=== Trotter local Android artifact build ==='
echo "Mode: $MODE"
echo "Channel: $BUILD_CHANNEL"
echo "Commit: $SOURCE_SHA"
echo "API: ${API_BASE_URL:-http://localhost:8000 (development fallback)}"
echo 'No app will be installed and nothing will be uploaded to Google Play.'

export NVM_DIR="$HOME/.nvm"
if [[ ! -s "$NVM_DIR/nvm.sh" ]]; then
  echo "ERROR: nvm not found at $NVM_DIR/nvm.sh" >&2
  exit 1
fi

# shellcheck source=/dev/null
. "$NVM_DIR/nvm.sh"
nvm use "$NVM_NODE_VERSION" >/dev/null

if [[ -n "$API_BASE_URL" ]]; then
  export EXPO_PUBLIC_TROTTER_API_URL="${API_BASE_URL%/}"
fi

export ANDROID_HOME="$HOME/Android/Sdk"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export ANDROID_NDK_HOME="$ANDROID_HOME/ndk/27.1.12297006"
export PATH="$HOME/.local/bin:$NVM_DIR/versions/node/v$NVM_NODE_VERSION/bin:$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
if [[ -d /usr/lib/jvm/java-17-openjdk-amd64 ]]; then
  export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
  export PATH="$JAVA_HOME/bin:$PATH"
fi
hash -r

for command_name in node npm npx java rsync unzip sha256sum install; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "ERROR: Required command not found: $command_name" >&2
    exit 1
  fi
done

if command -v node | grep -q '^/mnt/c/'; then
  echo "ERROR: WSL resolved Windows Node instead of the WSL runtime: $(command -v node)" >&2
  exit 1
fi

java_version="$(java -version 2>&1 | head -n 1)"
if [[ "$java_version" != *'17.'* ]]; then
  echo "ERROR: Java 17 is required; found: $java_version" >&2
  exit 1
fi

if [[ ! -d "$ANDROID_HOME" ]]; then
  echo "ERROR: Android SDK not found at $ANDROID_HOME" >&2
  exit 1
fi

echo
echo '=== Syncing the Windows mobile project into WSL ==='
if [[ -L "$PROJECT" ]]; then
  echo "ERROR: Refusing a symlinked WSL build destination: $PROJECT" >&2
  exit 1
fi

mkdir -p "$PROJECT"
home_real="$(cd "$HOME" && pwd -P)"
project_real="$(cd "$PROJECT" && pwd -P)"
if [[ "$project_real" != "$home_real/projects/trotter-mobile-v2" ]]; then
  echo "ERROR: Refusing an unexpected WSL build destination: $project_real" >&2
  exit 1
fi
PROJECT="$project_real"

rsync -a --delete --delete-excluded \
  --exclude node_modules \
  --exclude .expo \
  --exclude .gradle \
  --exclude dist \
  --exclude build \
  --exclude qa-screens \
  --exclude assets/photo-candidates \
  --exclude docs/design-directions \
  --exclude android/.gradle \
  --exclude android/build \
  --exclude android/app/.cxx \
  --exclude android/app/build \
  --exclude android/local.properties \
  "$SOURCE_MOBILE/" "$PROJECT/"

cd "$PROJECT"

echo
echo '=== Installing exact locked dependencies ==='
npm ci --include=dev --no-audit --no-fund

echo
echo '=== Validating the mobile source ==='
./node_modules/.bin/expo config --json >/dev/null
npm run typecheck
npx --yes expo-doctor

printf 'sdk.dir=%s\n' "$ANDROID_HOME" > android/local.properties
chmod +x android/gradlew

if [[ "$MODE" == 'aab' || "$MODE" == 'both' ]]; then
  signing_file='android/signing.properties'
  store_file="$(sed -n 's/^[[:space:]]*storeFile[[:space:]]*=[[:space:]]*//p' "$signing_file" | tail -n 1 | tr -d '\r')"
  if [[ -z "$store_file" || ! -f "android/$store_file" ]]; then
    echo "ERROR: Signing keystore was not found from storeFile in $signing_file" >&2
    exit 1
  fi
fi

mkdir -p "$WINDOWS_BUILDS" "$HOME/.cache"
STAMP="$(date -u +%Y-%m-%d_%H-%M-%SZ)"
BUILD_TAG="${SOURCE_SHA:0:12}"
if [[ "$BUILD_CHANNEL" == 'development' ]]; then
  BUILD_TAG="$BUILD_TAG-dev"
fi
TEMP_DIR="$(mktemp -d "$HOME/.cache/trotter-android-build.XXXXXX")"
trap 'rm -rf "$TEMP_DIR"' EXIT INT TERM HUP

gradle_tasks=()
if [[ "$MODE" == 'apk' || "$MODE" == 'both' ]]; then
  gradle_tasks+=(':app:assembleRelease')
fi
if [[ "$MODE" == 'aab' || "$MODE" == 'both' ]]; then
  gradle_tasks+=(':app:bundleRelease')
fi

effective_version_code="$VERSION_CODE"
if [[ "$effective_version_code" -le 0 ]]; then
  effective_version_code=1
fi

echo
echo '=== Building Android artifacts with Gradle ==='
(
  cd android
  ./gradlew --no-daemon clean "${gradle_tasks[@]}" -PtrotterVersionCode="$effective_version_code"
)

verify_artifact() {
  local source="$1"
  local extension="$2"

  if [[ ! -s "$source" ]]; then
    echo "ERROR: Gradle did not create a non-empty .$extension artifact: $source" >&2
    exit 1
  fi
  if ! unzip -tq "$source" >/dev/null; then
    echo "ERROR: The generated .$extension did not pass ZIP integrity validation." >&2
    exit 1
  fi
}

publish_artifact() {
  local source="$1"
  local timestamped_name="$2"
  local latest_name="$3"
  local timestamped_tmp="$WINDOWS_BUILDS/.$timestamped_name.tmp.$$"
  local latest_tmp="$WINDOWS_BUILDS/.$latest_name.tmp.$$"

  install -m 0644 "$source" "$timestamped_tmp"
  install -m 0644 "$source" "$latest_tmp"
  mv -f "$timestamped_tmp" "$WINDOWS_BUILDS/$timestamped_name"
  mv -f "$latest_tmp" "$WINDOWS_BUILDS/$latest_name"
  sha256sum "$WINDOWS_BUILDS/$timestamped_name" > "$WINDOWS_BUILDS/$timestamped_name.sha256"

  echo "Saved:  $timestamped_name"
  echo "Latest: $latest_name"
}

echo
echo '=== Publishing verified artifacts to Windows ==='
if [[ "$MODE" == 'apk' || "$MODE" == 'both' ]]; then
  apk_source='android/app/build/outputs/apk/release/app-release.apk'
  verify_artifact "$apk_source" 'apk'
  publish_artifact \
    "$apk_source" \
    "trotter-preview-$BUILD_TAG-$STAMP.apk" \
    'trotter-latest.apk'
fi

if [[ "$MODE" == 'aab' || "$MODE" == 'both' ]]; then
  aab_source='android/app/build/outputs/bundle/release/app-release.aab'
  verify_artifact "$aab_source" 'aab'
  publish_artifact \
    "$aab_source" \
    "trotter-play-vc$VERSION_CODE-$BUILD_TAG-$STAMP.aab" \
    'trotter-play-latest.aab'
fi

echo
echo '=== Android artifacts complete ==='
echo "WSL output folder: $WINDOWS_BUILDS"
echo 'Nothing was installed or uploaded.'
