import Foundation

// Run on the Mac: swiftc native-ios/shared/DreamShareInbox.swift native-ios/tests/main.swift -o /tmp/trotter-share-tests && /tmp/trotter-share-tests
func expect(_ condition: @autoclosure () -> Bool, _ message: String) {
  guard condition() else { fatalError(message) }
}
let owner = DreamShareOwner(apiBaseUrl: "https://api.example.test", ownerId: 1)
let other = DreamShareOwner(apiBaseUrl: "https://api.example.test", ownerId: 2)
let otherServer = DreamShareOwner(apiBaseUrl: "https://other.example.test", ownerId: 1)
let url = "https://www.instagram.com/reel/example_1/"
expect(DreamShareInbox.canonicalURL("Look! https://instagram.com/reels/example_1/?igsh=secret") == url, "canonical URL")
for invalid in ["https://instagram.com.evil.test/reel/a/", "https://instagram.com@evil.test/reel/a/", "file:///reel/a", "https://instagram.com:8443/reel/a/", "https://instagram.com/reel/a/more"] {
  expect(DreamShareInbox.canonicalURL(invalid) == nil, "must reject unrelated URLs")
}
var entries: [DreamShareReceipt] = []
let anonymous = try DreamShareInbox.capture(&entries, owner: nil, text: url, now: 1)
expect(anonymous.status == "sign_in", "signed-out save is retained")
DreamShareInbox.bind(&entries, owner: owner)
expect(entries[0].owner == owner && entries[0].status == "queued", "first sign-in binds anonymous save")
DreamShareInbox.bind(&entries, owner: other)
expect(entries[0].owner == owner, "switching account must never transfer an owned receipt")
expect(DreamShareInbox.claim(&entries, owner: other, now: 2).isEmpty, "wrong account cannot upload")
expect(DreamShareInbox.claim(&entries, owner: otherServer, now: 2).isEmpty, "same ID on another server cannot upload")
let claimed = DreamShareInbox.claim(&entries, owner: owner, now: 2)[0]
expect(DreamShareInbox.claim(&entries, owner: owner, now: 3).isEmpty, "active lease blocks duplicate workers")
DreamShareInbox.complete(&entries, owner: other, id: claimed.id, generation: claimed.generation, httpStatus: 200, itemId: 9, dreamId: nil, now: 3)
expect(entries[0].status == "uploading", "wrong account cannot finish receipt")
DreamShareInbox.complete(&entries, owner: owner, id: claimed.id, generation: claimed.generation - 1, httpStatus: 200, itemId: 9, dreamId: nil, now: 3)
expect(entries[0].status == "uploading", "stale generation cannot finish receipt")
DreamShareInbox.complete(&entries, owner: owner, id: claimed.id, generation: claimed.generation, httpStatus: 200, itemId: nil, dreamId: nil, now: 3)
expect(entries[0].status == "queued", "missing server receipt must not claim saved")
expect(entries[0].nextAttemptAt > 3, "retry has backoff")
let retry = DreamShareInbox.claim(&entries, owner: owner, now: 4)[0]
DreamShareInbox.complete(&entries, owner: owner, id: retry.id, generation: retry.generation, httpStatus: 200, itemId: 9, dreamId: 7, now: 5)
expect(entries[0].status == "saved" && entries[0].itemId == 9, "valid success is acknowledged")
let recapture = try DreamShareInbox.capture(&entries, owner: owner, text: "A place for later " + url, now: 6)
expect(entries.count == 1 && recapture.status == "queued" && recapture.generation > retry.generation, "richer re-share retries same receipt")
let next = DreamShareInbox.claim(&entries, owner: owner, now: 7)[0]
DreamShareInbox.complete(&entries, owner: owner, id: next.id, generation: next.generation, httpStatus: 401, itemId: nil, dreamId: nil, now: 8)
expect(entries[0].status == "sign_in" && entries[0].sourceUrl == url, "expired auth retains the source")
DreamShareInbox.bind(&entries, owner: owner)
entries[0].attempts = 8
expect(DreamShareInbox.claim(&entries, owner: owner, now: 9).isEmpty && entries[0].status == "failed", "retries are bounded")
let otherReceipt = try DreamShareInbox.capture(&entries, owner: other, text: url, now: 10)
let anotherServerReceipt = try DreamShareInbox.capture(&entries, owner: otherServer, text: url, now: 10)
let unownedReceipt = try DreamShareInbox.capture(&entries, owner: nil, text: url, now: 10)
let erased = DreamShareInbox.forget(&entries, owner: owner)
expect(erased == [anonymous.id], "erasure returns only the deleted owner's payload identifiers")
expect(Set(entries.map { $0.id }) == Set([otherReceipt.id, anotherServerReceipt.id, unownedReceipt.id]), "erasure preserves other accounts, servers, and anonymous captures")
expect(DreamShareInbox.forget(&entries, owner: owner).isEmpty, "repeated scoped erasure is safe")
print("iOS share inbox checks passed")
