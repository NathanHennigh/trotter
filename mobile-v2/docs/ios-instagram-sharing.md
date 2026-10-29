# iPhone Instagram sharing

The source implementation is in `native-ios/`. Expo's `plugins/withTrotterShareExtension.js` creates the native targets during iOS prebuild; edit these source templates rather than generated copies under `ios/`.

## What is included

- A native **Trotter** share extension for URL/text shares, using the existing Newsreader/DM Sans fonts, paper background, blue ink, and a compact save receipt. It does not boot React, wait for extraction, or require selecting a trip.
- The extension durably records the Instagram post/reel URL and any supplied text before showing confirmation. Parsing, matching, and categorisation use the existing `/dreams/share` backend.
- An App Group inbox with atomic writes, file protection, backup exclusion, and cross-process locking. Credentials are stored separately in a device-only shared Keychain item.
- Owner/server isolation, revision and upload-generation checks, deduplication, bounded retries, and preservation of pending links. An expired credential retains ownership; another account cannot claim those links. A truly signed-out capture is bound to the next verified account.
- File-backed background URLSession uploads. iOS may delay these, especially without connectivity; the app resumes pending work when opened. The receipt distinguishes “kept on this iPhone” from server-confirmed “saved”. It does not promise immediate upload while offline.
- A React Native bridge matching the existing Android API and an AppDelegate handler for system background-session completion. Sign-out blocks credentials before cancelling requests. Requests already accepted by the server can finish, but late callbacks cannot transfer receipts between accounts.
- After server-confirmed account deletion, the iOS bridge removes only that server/account's receipts and upload files, cancels their tasks, and clears their active credential. Opaque receipt-ID tombstones permit repeated cleanup of late file writes without retaining captions, URLs, or account identity. The optional cleanup method is not present in older Android builds; their local native receipt cleanup remains separate follow-up work.

## Build/signing

Default bundle identifiers:

- App: `com.trotter.mobilev2`
- Extension target: `TrotterShare`, bundle `com.trotter.mobilev2.ShareExtension`
- App Group: `group.com.trotter.mobilev2.dreamshare`
- Shared Keychain: `$(AppIdentifierPrefix)com.trotter.mobilev2.dreamshare`

Both targets must be provisioned by the same Apple team with the App Group and Keychain sharing enabled. The plugin supplies EAS extension metadata and entitlements. Xcode expands the actual signing prefix into both Info.plists; no team identifier or credential is hardcoded.

The plugin preserves other targets, entitlements, and EAS metadata, and is safe to rerun. It deliberately rejects an unrelated extension bundle identifier or an AppDelegate with a conflicting custom background-session handler rather than silently overwriting it.

Background URLSession follows redirects without calling the normal redirect delegate. The uploader uses the exact HTTPS API URL and checks the configured host at TLS authentication; the API endpoint should continue returning a direct response, never an external redirect.

## Validation and remaining device checks

Run on this checkout:

```sh
node --test scripts/testIosShareExtension.cjs scripts/testNativeDreamShare.cjs
```

This verifies actual node-xcode project mutations, target embedding, resources, idempotence, entitlements, metadata, AppDelegate dispatch, and JS bridge behavior on both native platforms. It does **not** compile Swift.

On the Mac, run the pure inbox behavior harness:

```sh
swiftc native-ios/shared/DreamShareInbox.swift native-ios/tests/main.swift -o /tmp/trotter-share-tests
/tmp/trotter-share-tests
```

Then build the iOS app and extension with Xcode. Verify on a signed physical iPhone:

1. Instagram post/reel URL and caption sharing; repeated shares and richer captions.
2. Close the receipt immediately; verify server receipt on returning to Dreams.
3. Airplane mode, relaunch, system-delayed upload, expired credentials, and explicit retry.
4. Sign out during queued/uploading work, switch accounts, and switch back; no other owner's receipt is visible or claimed.
5. Share while signed out, then sign in and verify the retained link.
6. Dynamic Type, VoiceOver, reduced motion, and actual share-sheet height.
7. Confirm App Group/Keychain access and background-session handoff in signed builds, not only Simulator.
8. Delete a disposable account while it has a queued share; verify its receipt/payload and Keychain credential disappear while another account's retained receipts remain. Simulate cleanup failure and confirm the app reports local cleanup failure while still signing out.

No native iOS compilation or physical-device result is claimed from the Windows implementation session.

References: [Apple shared extension storage and background transfers](https://developer.apple.com/library/archive/documentation/General/Conceptual/ExtensibilityPG/ExtensionScenarios.html), [background transfer limitations](https://developer.apple.com/documentation/foundation/downloading-files-in-the-background), [Expo app extension builds](https://docs.expo.dev/build-reference/app-extensions/).
