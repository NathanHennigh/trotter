# Trotter PC → Mac iPhone pipeline

This adapts Etch's existing Windows wrapper, SSH Mac build user, pinned Expo/EAS
tooling, persistent build sessions, artifact verification, and direct Apple upload.
The SSH alias remains `etch-mac`; Trotter uses its own paths and app identities.

| State | Trotter location |
| --- | --- |
| Maintained source | `.ios-remote/` in this repository |
| Mac helpers, config, locks and upload receipts | `~/.trotter-ios-remote/` |
| Dedicated Git checkout | `~/Developer/trotter-build` |
| React Native app within that checkout | `mobile-v2/` |
| Artifacts and logs | `~/TrotterBuilds/` |
| PC downloads | `.ios-remote/artifacts/` (ignored) |

The script uses `config.example.psd1` unless the ignored `config.psd1` exists.
The example points to the existing SSH alias and Trotter's current branch. Update
the branch intentionally when preparing a release. Do not point any path at Etch.

## Use the existing Mac

From the repository root in PowerShell:

```powershell
.\.ios-remote\trotter-ios.ps1 test-ssh
.\.ios-remote\trotter-ios.ps1 doctor-local
```

The doctor reports the installed toolchain and Expo session. It does not install
Xcode, overwrite signing credentials, or start a build. Normal helper installation
copies only maintained scripts into the dedicated Trotter helper directory.

## Compile the current working changes

The project currently includes uncommitted implementation work. A
simulator snapshot lets that exact source compile on the Mac without committing
or publishing unrelated changes:

```powershell
.\.ios-remote\trotter-ios.ps1 build-snapshot
.\.ios-remote\trotter-ios.ps1 snapshot-status
.\.ios-remote\trotter-ios.ps1 pull-snapshot
```

`snapshot` packages without transferring or building. Use `-SnapshotId <SHA256>`
with status/pull to select a previous run instead of the latest local snapshot.

The snapshot includes only selected `mobile-v2` source, scripts, native templates,
configuration and assets. It excludes environment files, signing keys, generated
Android/iOS projects, dependency folders and caches. Every file has a size and
SHA256 in `source-manifest.json`; its canonical JSON produces the content ID.
The Mac checks the archive digest, rejects paths/links outside the manifest, and
verifies all source bytes before extraction into a fresh directory. Builds stay
in a Trotter-specific persistent session with a recorded result and artifact hash.

Snapshot builds cannot submit to Apple. They may compile without the iOS Maps key,
which means map-provider configuration remains unverified. No placeholder key is
used. Signed release preflight continues to require the actual app configuration.

Simulator builds use local ad hoc signing to embed the Keychain and App Group
entitlements. This requires no Apple certificate or provisioning profile. Both
the build and smoke check inspect the compiled app and extension entitlements;
disabling signing completely would produce an app with broken secure storage.

The Mac can read optional `~/.trotter-ios-remote/build.env`, owned by its build user
with mode `600`, containing unquoted `KEY=value` lines. Accepted keys are
`EXPO_PUBLIC_TROTTER_API_URL`, `EXPO_PUBLIC_APPLE_SIGN_IN_ENABLED`,
`GOOGLE_MAPS_IOS_API_KEY`, `APPLE_TEAM_ID`, `APPLE_APP_ID_PREFIX`, and
`EAS_PROJECT_ID`. The snapshot default API is `https://trotter-api.thehennighs.com`.
This private file stays outside the repository and is never included in snapshots.

## Release workflow

Etch's exact-commit release rules remain in place: the local checkout must be
clean, the selected branch must be pushed, and both machines must agree on its
full commit SHA. The Mac checkout is detached at that SHA and never reset/cleaned
to discard work.

```powershell
.\.ios-remote\trotter-ios.ps1 setup
.\.ios-remote\trotter-ios.ps1 validate
.\.ios-remote\trotter-ios.ps1 build-local -Profile iphone-testflight
.\.ios-remote\trotter-ios.ps1 attach
.\.ios-remote\trotter-ios.ps1 pull-latest
```

Use `iphone-simulator` for an EAS simulator build, `iphone-development`
for registered devices, or `iphone-testflight` for an App Store archive. EAS
project/signing setup is separate from having access to the already-configured Mac.
Trotter needs its own main/extension bundle IDs, App Group and provisioning.
Follow `mobile-v2/docs/iphone-setup.md` for those identities and backend settings.

The direct uploader keeps Trotter-specific receipts keyed by artifact SHA256 and
Apple app/version/build. Upload is a separate explicit command:

```powershell
.\.ios-remote\trotter-ios.ps1 doctor-direct-submit
.\.ios-remote\trotter-ios.ps1 submit-local -Profile iphone-testflight
.\.ios-remote\trotter-ios.ps1 direct-submit-status
```

Reuse an existing App Store Connect API key only when its account/app permissions
allow Trotter; do not copy Etch's bundle identity, provisioning profile, Expo
project ID, Apple app record or upload receipts. The optional
`configure-direct-submit` action accepts an explicitly selected private key outside
the repository and installs it into Trotter's private helper directory. Never put
private key contents in chat, source, logs, or the snapshot.

## Simulator checks and recovery

`smoke-simulator -Profile iphone-simulator -SimulatorUdid <UDID>` verifies the
selected artifact's Trotter bundle ID and extension before installation. Use a
dedicated simulator named `Trotter…`; the wrapper never auto-selects Etch's booted
simulator. Evidence is copied to the ignored local artifact folder.

For a successful source snapshot, pass its full content ID:

```powershell
.\.ios-remote\trotter-ios.ps1 smoke-simulator -Profile iphone-simulator -SnapshotId <content SHA256> -SimulatorUdid <UDID>
```

The helper verifies the snapshot's recorded success and artifact SHA256 before
installing it. Without `-SnapshotId`, the clean, pushed commit checks still apply.

If SSH drops, reconnect to the persistent build session with `attach`; inspect
the recorded status before starting another build. If Apple upload outcome is
unknown, use `direct-submit-status`. Do not delete receipts or retry an upload
until Apple confirms what happened. No helper automatically publishes an app.

## Local validation

```powershell
node --test .ios-remote/test-snapshot.cjs
.\.ios-remote\test-wrapper.ps1
```

macOS/Xcode compilation and signed-device tests are separate evidence from these
packaging and script checks.
