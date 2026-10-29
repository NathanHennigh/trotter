#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

IPA="${1:?Pass the exact Trotter IPA path.}"
APP_DIRECTORY="${2:?Pass the matching checkout/mobile-v2 directory.}"
PROFILE="${3:?Pass the EAS build profile.}"
HERE="$(cd "$(dirname "$0")" && pwd)"
VALIDATOR="$HERE/artifact-validation.py"

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[[ "$PROFILE" == "iphone-testflight" ]] || die "Only iphone-testflight artifacts can be submitted to Apple."
[[ -s "$IPA" && ! -L "$IPA" ]] || die "IPA is missing, empty, or a symlink."
[[ -f "$APP_DIRECTORY/app.json" && -f "$APP_DIRECTORY/app.config.js" ]] || die "Matching Trotter app checkout is missing."
[[ -f "$VALIDATOR" ]] || die "artifact-validation.py is missing beside this helper."
command -v python3 >/dev/null || die "Python 3 is required."
command -v node >/dev/null || die "Node is required."

WORK="$(mktemp -d -t trotter-ipa-verify)"
trap 'rm -rf "$WORK"' EXIT
mkdir "$WORK/extracted"
python3 "$VALIDATOR" extract zip "$IPA" "$WORK/extracted"
python3 "$VALIDATOR" bundle zip "$WORK/extracted" iPhoneOS > "$WORK/bundle.json"
APP="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["app"])' "$WORK/bundle.json")"
EXTENSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["extension"])' "$WORK/bundle.json")"

# Read only the explicit build expectations. The complete Expo config can contain
# client keys, so it is never printed or passed through shell evaluation.
node - "$APP_DIRECTORY" > "$WORK/expected.json" <<'NODE'
const fs = require('node:fs'), path = require('node:path');
const root = path.resolve(process.argv[2]);
require(require.resolve('@expo/env', { paths: [root] })).load(root, { silent: true });
const base = JSON.parse(fs.readFileSync(path.join(root, 'app.json'), 'utf8')).expo;
const config = require(path.join(root, 'app.config.js'))({ config: base });
if (config.ios?.bundleIdentifier !== 'com.trotter.mobilev2') throw new Error('Checkout is not Trotter.');
const team = process.env.APPLE_TEAM_ID || config.ios.appleTeamId;
const api = process.env.EXPO_PUBLIC_TROTTER_API_URL;
if (!/^[A-Z0-9]{10}$/.test(team || '')) throw new Error('Configure the intended Apple team before verifying a release.');
if (!api) throw new Error('Configure the intended production API before verifying a release.');
process.stdout.write(JSON.stringify({ team_id: team, app_id_prefix: process.env.APPLE_APP_ID_PREFIX || team,
  api_url: api.replace(/\/+$/, ''), version: config.version }));
NODE

verify_target() {
  local label="$1" target="$2" extension_flag="${3:-}"
  local target_work="$WORK/$label"
  mkdir "$target_work"
  [[ -f "$target/embedded.mobileprovision" ]] || die "$label has no embedded provisioning profile."
  /usr/bin/codesign --verify --deep --strict --verbose=2 "$target"
  /usr/bin/codesign --display --entitlements - --xml "$target" > "$target_work/entitlements.plist" 2> "$target_work/entitlements.log"
  /usr/bin/codesign --display --verbose=4 "$target" 2> "$target_work/signature.txt"
  /usr/bin/codesign --display --extract-certificates "$target_work/certificate" "$target" 2> "$target_work/certificates.log"
  /usr/bin/security cms -D -i "$target/embedded.mobileprovision" > "$target_work/profile.plist"
  [[ -s "$target_work/certificate0" && -s "$target_work/certificate1" ]] || die "$label has no complete Apple signing chain."
  grep -Eq '^Authority=(Apple Distribution|iPhone Distribution):' "$target_work/signature.txt" || die "$label is not signed for Apple distribution."
  # Retain system trust verification. Never copy Etch's temporary-keychain
  # workaround or pin Trotter to a certificate that belongs to another app.
  local certificate_args=() certificate
  for certificate in "$target_work"/certificate[0-9]*; do certificate_args+=(-c "$certificate"); done
  /usr/bin/security verify-cert -p codeSign "${certificate_args[@]}" > "$target_work/trust.log" 2>&1 || die "$label signing certificate is not trusted by this Mac."
  /usr/bin/openssl x509 -inform DER -in "$target_work/certificate0" -checkend 0 -noout >/dev/null || die "$label signing certificate has expired."
  local validation_args=(signed "$target/Info.plist" "$target_work/entitlements.plist" "$target_work/profile.plist" "$target_work/certificate0" "$WORK/expected.json")
  [[ -z "$extension_flag" ]] || validation_args+=(--extension)
  python3 "$VALIDATOR" "${validation_args[@]}"
}

verify_target app "$APP"
verify_target share "$EXTENSION" extension
cmp -s "$WORK/app/certificate0" "$WORK/share/certificate0" || die "App and share extension use different signing certificates."

python3 - "$WORK/bundle.json" "$WORK/expected.json" "$APP/main.jsbundle" <<'PY'
import json, sys
from pathlib import Path
from urllib.parse import urlsplit
bundle = json.load(open(sys.argv[1])); expected = json.load(open(sys.argv[2]))
if bundle['version'] != expected['version']:
    raise SystemExit('IPA marketing version does not match the selected source checkout.')
url = urlsplit(expected['api_url'])
if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment or url.port or url.path not in ('', '/'):
    raise SystemExit('Production API must be a public HTTPS origin.')
script = Path(sys.argv[3])
if not script.is_file() or expected['api_url'].encode() not in script.read_bytes():
    raise SystemExit('Production API URL is absent from the bundled JavaScript. Do not upload.')
PY

printf 'ipa_path=%s\n' "$IPA"
printf 'ipa_bytes=%s\n' "$(stat -f '%z' "$IPA")"
printf 'ipa_sha256=%s\n' "$(shasum -a 256 "$IPA" | awk '{print $1}')"
python3 - "$WORK/bundle.json" "$WORK/expected.json" <<'PY'
import json, sys
bundle = json.load(open(sys.argv[1])); expected = json.load(open(sys.argv[2]))
for key in ('bundle_id', 'version', 'build'):
    print(key + '=' + bundle[key])
print('team_id=' + expected['team_id'])
print('extension_id=com.trotter.mobilev2.ShareExtension')
print('app_group=group.com.trotter.mobilev2.dreamshare')
print('verification=PASS')
PY
