# iPhone build and testing

The React Native app and API are shared with Android. iOS is generated from
`app.json`, `app.config.js`, `plugins/withTrotterShareExtension.js` and `native-ios/`.
The first release targets iPhone. The generated `ios/` folder is ignored; keep
native changes in the plugin/templates so local and cloud builds match.

## What is implemented

- Sign in with Apple and an explicit link-Apple flow for an existing Trotter account.
  Both entry points stay hidden until Trotter's Apple setup is verified and
  `EXPO_PUBLIC_APPLE_SIGN_IN_ENABLED=true` is explicitly set. Google is first;
  the welcome screen says only “Flight sync requires Gmail.” about email access.
- Native Instagram Share Extension, its App Group inbox, shared Keychain session,
  background upload integration, and the React Native bridge.
- iPhone maps configuration, universal links for shared-trip invitations, and an
  installation handoff with a real TestFlight/App Store URL when configured.
- Account deletion entry, confirmation and provider verification. Backend contract
  and migration details are in `backend/AUTH_CONTRACT.md`.
- Successful deletion clears the account's device share queue, Gmail recovery and
  home-airport preference. A token-free cleanup marker keeps sign-in blocked if
  device erasure fails; **Retry sign out** finishes the cleanup after a restart.
- Local configuration checks and separate simulator, development-device and
  TestFlight EAS profiles.
- Windows-to-Mac builds using Etch's existing SSH/toolchain setup, with separate
  Trotter helpers, source directories, artifacts and upload receipts.

The existing Mac pipeline completed a clean native Release build with Xcode 26.6
on October 27, 2026. The app and embedded share extension compile, and the
iPhone 17 Pro simulator (iOS 26.5) opens the welcome screen without the secure
storage error or JavaScript launch errors. Native inbox tests, generated-file
path checks and compiled simulator entitlements also pass.

Distribution signing and TestFlight delivery subsequently passed; physical iPhone testing is still pending. Trotter has its own Expo project
`@nathanhennigh/trotter-v2` (`99fd8582-8058-41da-b72f-bd09e78ac528`), linked in
`app.json` on October 28, 2026. Apple account setup is now complete:

| Item | Verified value |
| --- | --- |
| Apple team / App ID prefix | `BVA33376DZ` |
| App Store Connect draft | `6828049706`, **Trotter: Travel Together** |
| Main App ID record | `4Z8KF7VS48` |
| Share extension App ID record | `BJ4MG8BPN6` |
| Sign in with Apple key | `U8G7UQRCVD`, primary app is Trotter |
| Separate upload API key | `W2NUU24KD5`, Developer role |
| Distribution certificate | `B66PJ736HG`, expires October 28, 2027 |
| Main / extension App Store profiles | `MDHVGS8K2N` / `8C96R8D7SR` |

Both profiles were decoded and checked against the exact bundle IDs, shared App
Group, Keychain prefix and new certificate. The main profile also includes Apple
sign-in and Associated Domains. Both targets' build credentials are uploaded to
Trotter's Expo project. Etch's app identities, keys and profiles were not reused.
The store name includes a descriptive suffix because `Trotter` alone is already reserved;
the installed app remains named Trotter.

Google Maps SDK for iOS is enabled in the existing `trotter-494201` Google Cloud
project. `Trotter iOS Maps` (`40657e14-e60a-48db-98e7-561ffebe826c`) permits only
Maps SDK for iOS and bundle `com.trotter.mobilev2`. The key is stored in the ignored
Maps properties file and as a sensitive EAS variable in development, preview and
production. Those environments also have the production API URL and Apple login
disabled by default. `npm run ios:check` now passes with the production API URL.

The backend update and migration `0022_ios_auth_identities` are live. The Apple
challenge endpoint returns 200 and the association file advertises Trotter's
`/planner/open` route. Apple's token service accepts the client configuration
before rejecting a deliberately invalid test authorization code (`invalid_grant`).
That is a configuration check, not a completed user sign-in. Private keys are
stored outside Git with restricted file permissions. The deployment backup,
build, migration and rollback records are on the server under
`.cache/ios-apple/bf1849722d49/`.

The Mac reconnected on October 29, 2026. The newer welcome-screen snapshot
`a909ecd5c389357c732e156cea4884ba71ec735524caa8b3c7ebacc95bc401be` passed a clean
simulator launch with zero JavaScript errors. Google is first and the short Gmail
note is visible. Private build configuration is installed with mode 600, and the
separate Trotter upload key has verified access to app `6828049706`.

The isolated release branch is `codex/iphone-testflight-20261029`; source commit
`cf08cf66480587f053f52bba13919cbad1c7410d` includes the current mobile app and its
invitation-page validation dependency. The original working checkout was preserved.
Mac TypeScript, iPhone logic, generated native project, release configuration and
all 17 Expo Doctor checks passed. The EAS archive was inspected and contains the
mobile package, plugin and native sources. The directory inclusion rule must be
`!/mobile-v2` without a trailing slash because EAS checks directory paths before
traversing them. Remote build numbering keeps the exact source checkout clean.

The distribution certificate's original PKCS12 encoding was rejected by macOS
Keychain. It was re-encoded with macOS-compatible PKCS12 encryption using the same
private key, certificate and password. An isolated temporary Keychain confirmed a
valid code-signing identity before both Expo target credentials were updated.
Use `trotter-distribution-macos.p12`, not the original bundle, for local imports.
No trust checks or EAS tooling were bypassed or patched.

The signed archive succeeded and Apple accepted version **0.1.2 (2)** with no
validation or delivery errors on October 29, 2026. Delivery UUID:
`1536fd8a-78e3-4b32-b22f-b80062607c0e`. Apple processing finished successfully (`VALID`). No beta testers have been added yet.
The IPA is 70,976,938 bytes; SHA256:
`cea29558ae42eeecc352aa4acfaf68380590b2090e662d308b7d5a4d0b085855`.
The app and share extension passed strict signature, certificate trust, profile,
entitlement, version and production API checks. The compiled Google Maps key
matches the configured iOS key; 13 privacy manifests are present, including the
main app and Google Maps. Evidence and the signed IPA are preserved under
`.ios-remote/artifacts/iphone-beta-20261029/` in the original project.

Apple later emailed warning ITMS-90683 for build 2: the main app lacked
`NSLocationWhenInUseUsageDescription`. The linked map SDK requires it even though
Trotter currently disables user-location display and does not request location.
The maintained Expo configuration now includes the purpose string. Readiness,
generated-project and signed-IPA checks reject a missing or blank description;
the share extension does not require it. This adds no location request or tracking.

The corrected source is `c4de3efb61f497f7491ff1565cec3591ccd703da`. Mac validation
and native compilation passed for **0.1.2 (3)**. The exported main-app plist was
read back and matched the configured purpose exactly; the updated IPA gate also
correctly rejected build 2 for the missing key. Build 3 passed signing and Apple
pre-upload validation, then uploaded successfully as delivery
`93140d20-ba2a-4750-a9f7-3060d7caefa8`. Apple processing completed with `VALID`
and `READY_FOR_BETA_TESTING`; its delivery status reported no errors or warnings.
The IPA is 70,977,062 bytes; SHA256:
`0ec68ce79a789b0b55a5e80a545677c3645e8cff60cc9a6ca7ee1eb3fa5b9486`.
Evidence is preserved under `.ios-remote/artifacts/iphone-beta-build3-20261029/`.

The October 29 signed-in simulator review is recorded in
[iPhone simulator review](iphone-simulator-review-2026-10-29.md). Google sign-in,
populated Dreams/Maps, trip wallets, Passport, profile and Planner editing were
exercised. Safari-to-Trotter sharing of an existing Instagram post succeeded.
Source `8da6eee8eb79d26a26bbcf223335fcf8e4ba5f8e` fixes a native iOS globe
accessibility-range conversion error. Version **0.1.2 (4)** passed native
compilation and signed-IPA validation, then uploaded as delivery
`6dbdac36-b319-4118-944a-04327b1d5413`. Apple processing completed with `VALID`
and `READY_FOR_BETA_TESTING`; the delivery record had no errors or warnings.
IPA SHA256: `1639c13af7fc3eaa09dc0209e01fafa966dd7f85b0c55413c478d8c8b9f720b5`.
Evidence is under `.ios-remote/artifacts/iphone-beta-build4-20261029/`.
The simulator's software graphics backlog was subsequently fixed with a native
asynchronous frame barrier, limited to Apple Software Renderer. Flight paths,
year filters, rotation, tab returns and NASA imagery now update in the preview.
That follow-up is installed in the simulator and included in build 5 below;
build 4 does not include it. Physical graphics performance and the
unavailable software keyboard still prevent a complete device sign-off; see the
review's explicit limitations.

Version **0.1.2 (5)** was built from
`11dbef5f89eeae8a7a444d081ef26a7c0cd6e5d5`. Mac release checks, native compilation,
both signed-target checks and Apple's archive validation passed. Apple accepted
the upload as delivery `1ee47616-c049-4575-84cc-f0e6eff6c402`; processing is pending.
IPA SHA256: `7779479ea11550f77be0cf8865c03254b43c56ecbd3f054925f7994f8c1ee95b`.
The verified IPA, receipts and prepared beta description/testing notes are under
`.ios-remote/artifacts/iphone-beta-build5-20261029/` outside Git.

External testing is not configured or submitted. The upload API key's Developer
role cannot create an external beta group (Apple returned HTTP 403). The owner
will sign into App Store Connect later and create a dedicated Google review
account. Review email was supplied and saved in the private metadata draft;
a contact phone number is still needed. Continue with that browser session to
save test information, create Friends & Family, attach build 5, submit beta
review and prepare its invitation link. No tester invitation has been sent.

The certificate extractor uses `--extract-certificates=prefix`: with a separate
argument, macOS treated the prefix as another code path and failed. This was a
verification-script fix; the verified IPA bytes did not change.

Physical-iPhone checks remain pending. Real Apple sign-in/linking, Google Maps
display and Instagram sharing require device verification; Apple login remains
disabled by default. No friends have been invited and no App Store release was
submitted.

Verified source snapshot: `cf331dd7e19739c86dc791e88f386684f331a1b708892f68d2d867ee2ffbbc63`.
Final simulator artifact SHA256: `d577820197bd669e991972218b37d75f2b69764583b5aa81eccf477f39154fcc`.
Local launch evidence is under `.ios-remote/artifacts/simulator-cf331dd/`.

## Use the existing Etch Mac pipeline

The Mac and its build tools do not need to be set up again. Trotter reuses the
existing `etch-mac` SSH alias and build user, the pinned EAS CLI, persistent `tmux`
builds, artifact checks and direct Apple uploader. Trotter's source lives in the
`mobile-v2` subdirectory of its own repository.

| Purpose | Dedicated Trotter location |
| --- | --- |
| Helpers, build configuration and upload receipts | `~/.trotter-ios-remote/` |
| Exact-commit release checkout | `~/Developer/trotter-build` |
| Unsigned working-source snapshots | `~/.trotter-ios-remote/snapshots/` |
| Mac artifacts and logs | `~/TrotterBuilds/` |
| Windows downloads | `.ios-remote/artifacts/` (ignored) |

Etch's checkout, app identifiers, provisioning profiles and upload records remain
separate. From the **repository root** in PowerShell:

```powershell
.\.ios-remote\trotter-ios.ps1 test-ssh
.\.ios-remote\trotter-ios.ps1 doctor-local
.\.ios-remote\trotter-ios.ps1 build-snapshot
.\.ios-remote\trotter-ios.ps1 snapshot-status
.\.ios-remote\trotter-ios.ps1 pull-snapshot
```

The snapshot path compiles the current source, including uncommitted Swift and
plugin changes, as a simulator app without Apple distribution credentials. Only allowlisted app sources and
assets are transferred; environment files, signing credentials, dependencies and
generated native projects are excluded. The Mac verifies the archive and every
source file against a SHA256 manifest before extracting it into a fresh directory.
The persistent build records its final result and artifact hash. Use
`-SnapshotId <content SHA256>` with status or pull to select an earlier snapshot.

A simulator snapshot can compile without an iOS Maps key; that exercises the safe
map fallback and does not validate the Google Maps provider. Simulator compilation
also does not prove device signing, live Apple sign-in or Instagram sharing.
Local ad hoc signing is enabled so Xcode embeds working simulator Keychain and
App Group entitlements; it requires no Apple certificate or provisioning profile.

For releases, the wrapper requires a clean working tree, a pushed branch and the
same exact commit on Windows and Mac. After the Trotter configuration below exists:

```powershell
.\.ios-remote\trotter-ios.ps1 setup
.\.ios-remote\trotter-ios.ps1 validate
.\.ios-remote\trotter-ios.ps1 build-local -Profile iphone-testflight
.\.ios-remote\trotter-ios.ps1 attach
.\.ios-remote\trotter-ios.ps1 pull-latest
```

Uploading is a separate explicit action, `submit-local -Profile iphone-testflight`.
It validates Trotter's app/extension identity and signing, then keeps a receipt to
prevent accidental duplicate uploads. Use `doctor-direct-submit` before the first
upload and `direct-submit-status` to resolve an interrupted upload.

The ignored `.ios-remote/config.psd1` can override the checked-in example's branch
and host settings. Keep the dedicated Trotter paths. Full commands, snapshot
validation, simulator selection and recovery are documented in
[`../../.ios-remote/README.md`](../../.ios-remote/README.md).

## Configure the accounts once

Mac access does not create Trotter's Apple or Expo app. Use the intended owner's
existing Apple Developer team and Expo account, but register Trotter's own
identifiers together:

| Item | Identifier |
| --- | --- |
| Main app | `com.trotter.mobilev2` |
| Share extension | `com.trotter.mobilev2.ShareExtension` |
| App Group on both targets | `group.com.trotter.mobilev2.dreamshare` |
| Shared Keychain group on both targets | `$(AppIdentifierPrefix)com.trotter.mobilev2.dreamshare` |

Enable Sign in with Apple and Associated Domains on the main app. The share
extension needs its own provisioning profile. The config plugin declares both
targets to EAS; do not sign the extension with only the main app's profile.

The Expo project is linked in `app.json`; `npx eas-cli project:info` verifies it.
Use its existing project UUID rather than creating a second project. Create
an iOS Maps SDK key restricted to the main app's bundle identifier.

The Mac wrapper provides `eas-login` and `credentials` for its own Expo session and
Trotter signing setup. Use Trotter's dedicated upload key from the table above.
The Apple app record, Expo project, bundle IDs and provisioning profiles must
belong to Trotter. The server's Sign in with Apple key is separate from the upload
credential.

Trotter must use its own Sign in with Apple app identity and backend key
configuration. Reusing the Mac does not copy Etch's login credentials. Keep
`EXPO_PUBLIC_APPLE_SIGN_IN_ENABLED=false` until Trotter's real-device sign-in and
account-linking flows are verified; then enable it in the intended build
environment. Existing Apple accounts retain their account-deletion verification.

Copy `.env.example` to the ignored `.env` and fill these values:

- `EXPO_PUBLIC_TROTTER_API_URL`: the public HTTPS API origin.
- `GOOGLE_MAPS_IOS_API_KEY`: the separate iOS-restricted client key.
- `EAS_PROJECT_ID`: the real Expo project UUID.
- `APPLE_TEAM_ID`: the ten-character Apple team identifier.

Use matching values in the EAS `development` and `production` environments.
For Mac-local builds, these four values can also be placed in
`~/.trotter-ios-remote/build.env` as unquoted `KEY=value` lines, owned by the build
user with mode `600`. This file is private to the Mac and is not transferred in
source snapshots. The simulator snapshot defaults its public API origin to
`https://trotter-api.thehennighs.com`; signed release checks still require the
complete real configuration.
The iOS Maps key is compiled into the client; its bundle restriction protects it.
Never put the server Places key or Apple private signing key into Expo public
variables or application source.

## Backend configuration

Deploy the new API and apply its migrations before testing Apple sign-in. Set:

- `APPLE_CLIENT_ID=com.trotter.mobilev2`
- `APPLE_BUNDLE_ID=com.trotter.mobilev2`
- `APPLE_TEAM_ID` and `APPLE_KEY_ID` from the Apple Developer account.
- `APPLE_PRIVATE_KEY_FILE`: a mounted Sign in with Apple `.p8` private key.
- `APPLE_APP_ID_PREFIX`: only when the provisioned App ID prefix differs from the
  team identifier; otherwise leave empty.
- `IOS_APP_DOWNLOAD_URL`: leave empty until there is a real TestFlight public link;
  later use the App Store link. Only exact Apple hosts are accepted.

For the home-server Docker deployment, the optional `deploy/compose.ios.yml`
overlay mounts `deploy/secrets/apple_private_key` into the API and worker. The
base deployment continues to work without that file. `deploy/scripts/deploy.sh`
automatically includes the overlay when Apple IDs are configured and rejects an
incomplete setup. Include both compose files on manual restart commands. The
entrypoint reads the mode-600 private key before dropping root privileges, so the
API and worker do not need a world-readable secret file. Keep the private key out
of Git and command output.

The API serves `/.well-known/apple-app-site-association`. Publish this endpoint
on the API domain over HTTPS without an authentication challenge or redirect.
It advertises only `/planner/open`, not OAuth routes. Until the real Apple
identity is set, it returns an uncached 503 instead of a false association.
Apple may cache association files, so test installation after deployment.

An invitation stays in the URL fragment. After installing from TestFlight, the
person returns to the invitation and taps **Open in Trotter**. This does not claim
automatic invitation delivery across a new installation. Joining still requires
explicit confirmation.

## Direct local testing on the Mac

The existing Mac already has Xcode, Node and CocoaPods; use `doctor-local` to check
them before a build. For interactive testing directly on the Mac, use the
dedicated Trotter checkout and run these from `mobile-v2`:

```sh
npm ci
npm run typecheck
npm run test:iphone
npm run ios:check:simulator
npm run ios:verify-prebuild
npx expo prebuild --platform ios
npx expo run:ios
```

`ios:verify-prebuild` creates an isolated generated project and verifies the
extension target, entitlements, fonts, maps setup and link forwarding. It does
not run Xcode compilation. `expo run:ios` does the actual local compile.

To install a local development build on a connected iPhone:

```sh
npm run ios:check
npx expo run:ios --device
```

Use Xcode's Signing & Capabilities on both targets if manual provisioning is
needed. Commit fixes back to the plugin/templates, not only the generated Xcode
project. Avoid `expo prebuild --clean` without `--platform ios`: the Android tree
contains custom native work.

## Cloud builds and TestFlight

These can be started from Windows after the accounts and configuration exist:

```sh
npm run ios:check
npx eas-cli build --platform ios --profile iphone-development
npx eas-cli build --platform ios --profile iphone-testflight
npx eas-cli submit --platform ios --profile iphone-testflight
```

For a simulator artifact use `--profile iphone-simulator`. EAS signs the app and
extension separately. The root `.easignore` keeps generated iOS files, private
credentials, caches and unrelated server files out of the archive. The maintained
Android native tree is retained for Android builds; the iOS project is generated
for iOS builds. Before the first cloud build, inspect the archive using
`eas build:inspect --platform ios --profile iphone-testflight --stage archive`.

Create/select the real App Store Connect app during submission. There is no
invented `ascAppId` in the repository. The first external TestFlight build needs
Apple review. Do not invite friends until the device checks below pass.

## Device checks before friends test

1. New Apple account, existing Google account, explicit Apple linking, cancellation,
   account switching and Gmail connection with Apple Hide My Email.
2. Instagram reel/post sharing while Trotter is running, closed, signed out and
   offline. Verify duplicate saves, reconnect, account isolation and receipt copy.
3. Shared-trip invitation on cold launch, after sign-in, after install and after
   expiry; confirm that opening a link does not itself join a trip.
4. Dreams maps and markers, globe lifecycle, postcard flip, image loading, keyboard
   fields, safe areas, sheet transitions, itinerary drag and day navigation.
5. Account deletion using disposable test accounts, including provider revocation
   and the documented shared-trip consequences.

Review Xcode's merged privacy report and App Store Connect privacy answers before
submission. The app manifest currently declares React Native's UserDefaults and
file-timestamp uses; third-party SDK manifests are aggregated by CocoaPods. This
does not substitute for disclosures about account data, saved content, flight
imports, or the map SDK. Configure the real privacy-policy and support URLs in
App Store Connect.

## Verification recorded on Windows/WSL

- Configuration, invitation parsing/handoff and AASA tests passed.
- TypeScript checks and iOS/web JavaScript bundle exports passed. A bundle export
  is not an IPA or a Swift compilation.
- The final backend auth, account deletion, sharing, Planner, invitation landing
  and Apple association run passed 193 tests, including signature/nonce verification
  with generated RSA keys. Apple service requests were mocked. The frontend and
  iOS configuration suite passed 126 tests.
- Actual Expo iOS prebuild succeeded in an isolated Linux fixture, including a
  repeat run to verify that targets/resources are not duplicated.
- Generated Xcode project checks confirmed extension embedding, shared App Group
  and Keychain entitlements, Apple sign-in, universal-link forwarding, fonts, and
  one Google Maps pod/key initialization.
- CocoaPods installation and native Release compilation subsequently passed on
  the Mac, including simulator entitlements and a clean launch. Distribution
  signing, the newest UI snapshot, live Apple OAuth and physical iPhone behavior
  remain for the next Mac/device pass.
- October 28 account setup: 152 backend auth/deletion/sharing/link checks and 36
  mobile account/configuration/recovery checks passed. The production identity
  migration, healthy API/workers, Apple challenge endpoint and invitation
  association response were verified after deployment. These are not an iPhone
  end-to-end sign-in test.
- The remote wrapper's clean/pushed/exact-commit guards and six snapshot
  packaging/extraction checks pass locally. These cover uncommitted native source,
  secret/generated-file exclusions, content identity, existing destinations,
  traversal, symlinks and Mac filename collisions; they are not simulator results.

References: [Expo Apple authentication](https://docs.expo.dev/versions/v54.0.0/sdk/apple-authentication/),
[EAS app extensions](https://docs.expo.dev/build-reference/app-extensions/),
[iOS build process](https://docs.expo.dev/build-reference/ios-builds/),
[Apple associated domains](https://developer.apple.com/documentation/xcode/supporting-associated-domains),
[Expo privacy manifests](https://docs.expo.dev/guides/apple-privacy/).
