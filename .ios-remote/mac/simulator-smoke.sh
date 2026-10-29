#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

ARTIFACT="${1:?Pass the exact Trotter simulator .tar.gz artifact.}"
UDID="${2:?Pass the dedicated Trotter iPhone Simulator UDID.}"
OUTPUT_ROOT="${3:-$HOME/TrotterBuilds/simulator-smoke}"
SHARED_PERMISSION="${4:-}"
HERE="$(cd "$(dirname "$0")" && pwd)"
VALIDATOR="$HERE/artifact-validation.py"
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[[ "$UDID" =~ ^[0-9A-Fa-f-]{36}$ ]] || die "A simulator UDID is required."
[[ -z "$SHARED_PERMISSION" || "$SHARED_PERMISSION" == "--allow-shared-simulator" ]] || die "Unknown simulator option."
[[ -f "$ARTIFACT" && ! -L "$ARTIFACT" ]] || die "Simulator artifact is missing or is a symlink."
[[ -f "$VALIDATOR" ]] || die "artifact-validation.py is missing beside this helper."
for tool in python3 xcrun; do command -v "$tool" >/dev/null || die "Missing $tool."; done

mkdir -p "$OUTPUT_ROOT"
run_dir="$(mktemp -d "$OUTPUT_ROOT/$(date -u +%Y%m%dT%H%M%SZ).XXXXXX")"
extract_dir="$run_dir/extracted"
screenshot="$run_dir/trotter-launch.png"
app_log="$run_dir/trotter-launch.log"
mkdir "$extract_dir"
python3 "$VALIDATOR" extract tar "$ARTIFACT" "$extract_dir"
python3 "$VALIDATOR" bundle tar "$extract_dir" iPhoneSimulator > "$run_dir/bundle.json"
app_path="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["app"])' "$run_dir/bundle.json")"
python3 "$VALIDATOR" simulator-entitlements "$app_path"
bundle_id="com.trotter.mobilev2"
executable="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["executable"])' "$run_dir/bundle.json")"

# Validate the exact artifact and selected simulator before any simulator state
# is changed. Etch's installed app can never be used as this command's target.
xcrun simctl list devices available -j > "$run_dir/devices.json"
python3 - "$run_dir/devices.json" "$UDID" "$SHARED_PERMISSION" <<'PY'
import json, sys
devices = json.load(open(sys.argv[1]))['devices']
matches = [(runtime, device) for runtime, rows in devices.items() for device in rows if device.get('udid') == sys.argv[2]]
if len(matches) != 1:
    raise SystemExit('Selected simulator is not available.')
runtime, device = matches[0]
if '.iOS-' not in runtime or not device.get('isAvailable', False) or '.iPhone-' not in device.get('deviceTypeIdentifier', ''):
    raise SystemExit('Selected device must be an available iPhone Simulator.')
if not device.get('name', '').startswith('Trotter') and sys.argv[3] != '--allow-shared-simulator':
    raise SystemExit('Use a dedicated simulator named Trotter, or explicitly allow this selected shared simulator.')
PY

if ! xcrun simctl boot "$UDID" 2> "$run_dir/boot-error.log"; then
  xcrun simctl list devices available -j > "$run_dir/after-boot.json"
  python3 - "$run_dir/after-boot.json" "$UDID" <<'PY'
import json, sys
devices = [d for group in json.load(open(sys.argv[1]))['devices'].values() for d in group]
if not any(d.get('udid') == sys.argv[2] and d.get('state') == 'Booted' for d in devices):
    raise SystemExit('The selected simulator could not be booted.')
PY
fi
python3 - "$UDID" <<'PY'
import subprocess, sys
try:
    subprocess.run(['xcrun', 'simctl', 'bootstatus', sys.argv[1], '-b'], check=True, timeout=900)
except subprocess.TimeoutExpired:
    raise SystemExit('Simulator did not finish booting within 15 minutes.')
PY

# Fresh installation is deliberate and scoped to Trotter only.
xcrun simctl terminate "$UDID" "$bundle_id" >/dev/null 2>&1 || true
xcrun simctl uninstall "$UDID" "$bundle_id" >/dev/null 2>&1 || true
xcrun simctl install "$UDID" "$app_path"
launch_started="$(date '+%Y-%m-%d %H:%M:%S')"
launch_output="$(xcrun simctl launch "$UDID" "$bundle_id")"
printf '%s\n' "$launch_output"
app_pid="${launch_output##*: }"
[[ "$app_pid" =~ ^[0-9]+$ ]] || die "Simulator did not return a process ID."
sleep 8
xcrun simctl io "$UDID" screenshot "$screenshot"
xcrun simctl spawn "$UDID" log show --style compact --start "$launch_started" --predicate "process == \"$executable\"" > "$app_log" 2>&1 || die "Simulator launch logs could not be read. See the saved log."
js_error_count="$(grep -Ec ' [EF] .*\[com\.facebook\.react\.log:javascript\]' "$app_log" || true)"
process_status=exited
kill -0 "$app_pid" 2>/dev/null && process_status=running
printf 'SIMULATOR_UDID=%s\nAPP_PATH=%s\nBUNDLE_ID=%s\nAPP_PID=%s\nAPP_STATUS=%s\nAPP_JS_ERRORS=%s\nSCREENSHOT=%s\nLOG=%s\n' \
  "$UDID" "$app_path" "$bundle_id" "$app_pid" "$process_status" "$js_error_count" "$screenshot" "$app_log"
[[ "$process_status" == running ]] || die "Trotter exited before the launch screenshot was captured."
[[ "$js_error_count" == 0 ]] || die "Trotter emitted JavaScript errors during launch. See the saved launch log."
