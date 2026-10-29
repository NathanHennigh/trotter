import Foundation
import Security
import Darwin

/// Atomic JSON plus a POSIX lock: the app and share extension are separate processes.
/// Credentials live only in a device-only shared Keychain item, never in the inbox.
final class DreamShareStore {
  static let shared = DreamShareStore()
  struct State: Codable {
    var bridgeId: String?
    var revision = 0
    var blocked = true
    var captureOwner: DreamShareOwner?
    var erasedReceiptIDs: [String]?
    var entries: [DreamShareReceipt] = []
  }
  private let queueLock = NSRecursiveLock()
  private var memoryBlocked = false
  static var now: Double { Date().timeIntervalSince1970 * 1000 }

  func directory() throws -> URL {
    guard let root = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: TrotterShareConfiguration.appGroup) else { throw DreamShareError.unavailable }
    let folder = root.appendingPathComponent("DreamShare", isDirectory: true)
    try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true,
      attributes: [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication])
    var values = URLResourceValues(); values.isExcludedFromBackup = true
    var protectedFolder = folder; try protectedFolder.setResourceValues(values)
    return folder
  }

  private func locked<T>(_ body: (inout State) throws -> T) throws -> T {
    queueLock.lock(); defer { queueLock.unlock() }
    let folder = try directory()
    let descriptor = open(folder.appendingPathComponent("inbox.lock").path, O_CREAT | O_RDWR, S_IRUSR | S_IWUSR)
    guard descriptor >= 0 else { throw DreamShareError.unavailable }
    defer { close(descriptor) }
    guard flock(descriptor, LOCK_EX) == 0 else { throw DreamShareError.unavailable }
    defer { flock(descriptor, LOCK_UN) }
    let file = folder.appendingPathComponent("inbox.json")
    var state: State
    if FileManager.default.fileExists(atPath: file.path) {
      // Corruption must never silently erase saved links.
      state = try JSONDecoder().decode(State.self, from: Data(contentsOf: file))
    } else { state = State() }
    let result = try body(&state)
    try JSONEncoder().encode(state).write(to: file, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
    return result
  }

  private var keychainQuery: [String: Any] {
    [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: "trotter.dream-share.v1",
      kSecAttrAccount as String: "active-session", kSecAttrAccessGroup as String: TrotterShareConfiguration.keychainGroup]
  }
  private func credential() throws -> DreamShareSession? {
    var query = keychainQuery
    query[kSecReturnData as String] = true; query[kSecMatchLimit as String] = kSecMatchLimitOne
    var result: CFTypeRef?
    let status = SecItemCopyMatching(query as CFDictionary, &result)
    if status == errSecItemNotFound { return nil }
    guard status == errSecSuccess, let data = result as? Data else { throw DreamShareError.invalidSession }
    return try JSONDecoder().decode(DreamShareSession.self, from: data)
  }
  private func writeCredential(_ session: DreamShareSession) throws {
    let attributes: [String: Any] = [kSecValueData as String: try JSONEncoder().encode(session),
      kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly]
    let status = SecItemUpdate(keychainQuery as CFDictionary, attributes as CFDictionary)
    if status == errSecItemNotFound {
      guard SecItemAdd(keychainQuery.merging(attributes) { _, new in new } as CFDictionary, nil) == errSecSuccess else { throw DreamShareError.invalidSession }
    } else if status != errSecSuccess { throw DreamShareError.invalidSession }
  }
  private func active(_ state: State) throws -> DreamShareSession? {
    guard !state.blocked, !memoryBlocked else { return nil }
    return try credential()
  }

  func attachBridge(_ id: String) throws {
    try locked { state in state.bridgeId = id; state.revision = 0 }
  }
  func invalidate(revision: Int, bridgeId: String) throws -> Bool {
    // Persist the tombstone before deleting the credential, so failure is fail-closed.
    let shouldDelete = try locked { state -> Bool in
      guard state.bridgeId == bridgeId, revision >= state.revision else { return false }
      state.revision = revision; state.blocked = true; memoryBlocked = true
      state.captureOwner = nil
      for index in state.entries.indices where state.entries[index].status == "uploading" {
        state.entries[index].generation += 1
        state.entries[index].status = "sign_in"
        state.entries[index].leaseUntil = 0
      }
      return true
    }
    guard shouldDelete else { return false }
    let status = SecItemDelete(keychainQuery as CFDictionary)
    guard status == errSecSuccess || status == errSecItemNotFound else { throw DreamShareError.invalidSession }
    return true
  }
  func configure(apiBaseUrl: String, ownerId: Int, token: String, revision: Int, bridgeId: String) throws {
    let base = apiBaseUrl.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
    guard let url = URLComponents(string: base), url.scheme == "https", url.host != nil,
      url.user == nil, url.password == nil, url.query == nil, url.fragment == nil,
      ownerId > 0, !token.isEmpty, token.rangeOfCharacter(from: .whitespacesAndNewlines) == nil else { throw DreamShareError.invalidSession }
    try locked { state in
      guard state.bridgeId == bridgeId, state.revision == revision else { return }
      let owner = DreamShareOwner(apiBaseUrl: base, ownerId: ownerId)
      let old = try credential()
      let generation = old?.owner == owner && old?.token == token ? old!.generation : UUID().uuidString
      try writeCredential(DreamShareSession(owner: owner, token: token, generation: generation))
      DreamShareInbox.bind(&state.entries, owner: owner)
      state.captureOwner = owner
      state.blocked = false; memoryBlocked = false
    }
  }
  func session() throws -> DreamShareSession? { try locked { try active($0) } }
  func capture(_ text: String) throws -> DreamShareReceipt {
    try locked { state in
      // Expired credentials still identify the owner. A 401 must not turn their
      // next saved reel into an anonymous link transferable to another account.
      let session = try? active(state)
      let owner = session?.owner ?? state.captureOwner
      let receipt = try DreamShareInbox.capture(&state.entries, owner: owner, text: text, now: Self.now)
      if session == nil, let index = state.entries.firstIndex(where: { $0.id == receipt.id }), state.entries[index].status != "saved" {
        state.entries[index].status = "sign_in"
        return state.entries[index]
      }
      return receipt
    }
  }
  func visible() throws -> [DreamShareReceipt] {
    try locked { state in
      guard let session = try active(state) else { return [] }
      return state.entries.filter { $0.owner == session.owner }
    }
  }
  func receipt(_ id: String) throws -> DreamShareReceipt? {
    try locked { $0.entries.first { $0.id == id } }
  }
  func claim() throws -> (DreamShareSession, [DreamShareReceipt])? {
    try locked { state in
      guard let session = try active(state) else { return nil }
      return (session, DreamShareInbox.claim(&state.entries, owner: session.owner, now: Self.now))
    }
  }
  func complete(sessionGeneration: String, id: String, generation: Int, httpStatus: Int, itemId: Int?, dreamId: Int?) throws {
    try locked { state in
      guard let session = try active(state), session.generation == sessionGeneration else { return }
      DreamShareInbox.complete(&state.entries, owner: session.owner, id: id, generation: generation,
        httpStatus: httpStatus, itemId: itemId, dreamId: dreamId, now: Self.now)
      if httpStatus == 401 || httpStatus == 403 {
        state.blocked = true
        for index in state.entries.indices where state.entries[index].owner == session.owner && state.entries[index].status == "uploading" {
          state.entries[index].generation += 1
          state.entries[index].status = "sign_in"
          state.entries[index].leaseUntil = 0
        }
      }
    }
  }
  func retry(_ id: String) throws {
    try locked { state in
      guard let session = try active(state), let index = state.entries.firstIndex(where: {
        $0.id == id && $0.owner == session.owner && $0.status != "saved"
      }) else { return }
      DreamShareInbox.reset(&state.entries[index])
    }
  }
  func acknowledge(_ id: String) throws {
    try locked { state in
      guard let session = try active(state) else { return }
      state.entries.removeAll { $0.id == id && $0.owner == session.owner && $0.status == "saved" }
    }
  }

  /// Called only after the backend confirms this account was deleted. Retain a
  /// payload-cleanup ledger so a filesystem failure can be retried on app open.
  func forgetAccount(apiBaseUrl: String, ownerId: Int) throws -> (Set<String>, String?) {
    let base = apiBaseUrl.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
    guard let url = URLComponents(string: base), url.scheme == "https", url.host != nil,
      url.user == nil, url.password == nil, url.query == nil, url.fragment == nil, ownerId > 0 else { throw DreamShareError.invalidSession }
    let owner = DreamShareOwner(apiBaseUrl: base, ownerId: ownerId)
    let removed = try locked { state -> (Set<String>, String?) in
      let session = try credential()
      let generation = session?.owner == owner ? session?.generation : nil
      if generation != nil {
        state.blocked = true; state.revision += 1; memoryBlocked = true
      }
      if state.captureOwner == owner { state.captureOwner = nil }
      let ids = Set(DreamShareInbox.forget(&state.entries, owner: owner))
      state.erasedReceiptIDs = Array(Set(state.erasedReceiptIDs ?? []).union(ids))
      return (ids, generation)
    }
    if removed.1 != nil {
      let status = SecItemDelete(keychainQuery as CFDictionary)
      guard status == errSecSuccess || status == errSecItemNotFound else { throw DreamShareError.invalidSession }
    }
    return removed
  }

  func cleanErasedPayloads() throws {
    try locked { state in
      let ids = Set((state.erasedReceiptIDs ?? []).filter { UUID(uuidString: $0) != nil })
      guard !ids.isEmpty else { return }
      let folder = try directory()
      for file in try FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: nil) {
        let name = file.lastPathComponent
        guard name.hasSuffix(".json"), name.count > 37 else { continue }
        let receiptId = String(name.prefix(36))
        let suffix = String(name.dropFirst(37).dropLast(5))
        guard ids.contains(receiptId), name[name.index(name.startIndex, offsetBy: 36)] == "-", Int(suffix) != nil else { continue }
        try FileManager.default.removeItem(at: file)
      }
      // Keep opaque receipt-ID tombstones. A suspended extension can finish an
      // already-started file write after cancellation; later app opens sweep it
      // again without retaining the URL, caption, or account identity.
      state.erasedReceiptIDs = Array(ids)
    }
  }
}
