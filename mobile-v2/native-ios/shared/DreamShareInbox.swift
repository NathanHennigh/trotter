import Foundation

struct DreamShareOwner: Codable, Equatable {
  let apiBaseUrl: String
  let ownerId: Int
}

struct DreamShareSession: Codable, Equatable {
  let owner: DreamShareOwner
  let token: String
  let generation: String
}

struct DreamShareReceipt: Codable {
  let id: String
  let sourceUrl: String
  var sharedText: String
  var owner: DreamShareOwner?
  var status: String
  let createdAt: Double
  var generation = 1
  var attempts = 0
  var leaseUntil: Double = 0
  var nextAttemptAt: Double = 0
  var itemId: Int?
  var dreamId: Int?
  var message: String?

  var bridgeValue: [String: Any] {
    var value: [String: Any] = ["id": id, "sourceUrl": sourceUrl, "sharedText": sharedText,
      "status": status, "createdAt": createdAt]
    if let owner = owner { value["ownerId"] = owner.ownerId }
    if let itemId = itemId { value["itemId"] = itemId }
    if let dreamId = dreamId { value["dreamId"] = dreamId }
    if let message = message { value["message"] = message }
    return value
  }
}

enum DreamShareError: LocalizedError {
  case invalidLink, full, unavailable, invalidSession
  var errorDescription: String? {
    switch self {
    case .invalidLink: return "Share an Instagram post or reel link to save it to Dreams."
    case .full: return "Your links are safe. Open Dreams to finish sending them before adding more."
    case .unavailable: return "Your link could not be kept on this phone. Please try sharing it again."
    case .invalidSession: return "Open Trotter and sign in to enable sharing."
    }
  }
}

/// Pure queue rules shared by the extension and the app. Times are milliseconds.
enum DreamShareInbox {
  /// Account erasure is explicitly scoped to both backend and owner ID.
  static func forget(_ entries: inout [DreamShareReceipt], owner: DreamShareOwner) -> [String] {
    let removed = entries.filter { $0.owner == owner }.map { $0.id }
    entries.removeAll { $0.owner == owner }
    return removed
  }

  static func canonicalURL(_ text: String) -> String? {
    // Reject lookalike hosts, credentials, file URLs, and tracking query strings.
    guard let detector = try? NSDataDetector(types: NSTextCheckingResult.CheckingType.link.rawValue) else { return nil }
    for match in detector.matches(in: text, range: NSRange(text.startIndex..., in: text)) {
      guard let url = match.url, ["https", "http"].contains(url.scheme?.lowercased() ?? ""),
        ["instagram.com", "www.instagram.com"].contains(url.host?.lowercased() ?? ""),
        url.user == nil, url.password == nil, url.port == nil else { continue }
      let parts = url.path.split(separator: "/")
      guard parts.count == 2, ["reel", "reels", "p", "tv"].contains(parts[0].lowercased()),
        parts[1].range(of: "^[A-Za-z0-9_-]+$", options: .regularExpression) != nil else { continue }
      let kind = parts[0].lowercased() == "reels" ? "reel" : parts[0].lowercased()
      return "https://www.instagram.com/\(kind)/\(parts[1])/"
    }
    return nil
  }

  static func bind(_ entries: inout [DreamShareReceipt], owner: DreamShareOwner) {
    for index in entries.indices {
      if entries[index].owner == nil { entries[index].owner = owner }
      if entries[index].owner == owner && entries[index].status == "sign_in" {
        reset(&entries[index])
      }
    }
  }

  static func capture(_ entries: inout [DreamShareReceipt], owner: DreamShareOwner?, text: String, now: Double) throws -> DreamShareReceipt {
    guard let url = canonicalURL(text) else { throw DreamShareError.invalidLink }
    entries.removeAll { $0.status == "saved" && now - $0.createdAt > 7 * 86_400_000 }
    let saved = entries.filter { $0.status == "saved" }.sorted { $0.createdAt > $1.createdAt }
    let retainedSaved = Set(saved.prefix(100).map { $0.id })
    entries.removeAll { $0.status == "saved" && !retainedSaved.contains($0.id) }
    let caption = String(text.trimmingCharacters(in: .whitespacesAndNewlines).prefix(60_000))
    if let index = entries.firstIndex(where: { $0.sourceUrl == url && $0.owner == owner }) {
      if caption.count > entries[index].sharedText.count || ["failed", "saved"].contains(entries[index].status) {
        if caption.count > entries[index].sharedText.count { entries[index].sharedText = caption }
        reset(&entries[index])
      }
      return entries[index]
    }
    guard entries.filter({ $0.status != "saved" }).count < 100 else { throw DreamShareError.full }
    let receipt = DreamShareReceipt(id: UUID().uuidString, sourceUrl: url, sharedText: caption,
      owner: owner, status: owner == nil ? "sign_in" : "queued", createdAt: now)
    entries.append(receipt)
    return receipt
  }

  static func reset(_ receipt: inout DreamShareReceipt) {
    receipt.generation += 1
    receipt.status = receipt.owner == nil ? "sign_in" : "queued"
    receipt.attempts = 0; receipt.leaseUntil = 0; receipt.nextAttemptAt = 0
    receipt.itemId = nil; receipt.dreamId = nil; receipt.message = nil
  }

  static func claim(_ entries: inout [DreamShareReceipt], owner: DreamShareOwner, now: Double) -> [DreamShareReceipt] {
    var claimed: [DreamShareReceipt] = []
    for index in entries.indices where entries[index].owner == owner {
      let pending = entries[index].status == "queued" || (entries[index].status == "uploading" && entries[index].leaseUntil <= now)
      guard pending else { continue }
      if entries[index].attempts >= 8 {
        entries[index].status = "failed"
        entries[index].message = "Kept on this phone. Open Dreams to retry sending it."
        continue
      }
      // A killed process's old completion cannot overwrite this new lease.
      entries[index].generation += 1
      entries[index].attempts += 1
      entries[index].status = "uploading"
      entries[index].leaseUntil = max(now, entries[index].nextAttemptAt) + 15 * 60_000
      claimed.append(entries[index])
    }
    return claimed
  }

  static func complete(_ entries: inout [DreamShareReceipt], owner: DreamShareOwner, id: String,
    generation: Int, httpStatus: Int, itemId: Int?, dreamId: Int?, now: Double) {
    guard let index = entries.firstIndex(where: { $0.id == id && $0.owner == owner && $0.generation == generation }) else { return }
    entries[index].leaseUntil = 0
    if (200...299).contains(httpStatus), let itemId = itemId, itemId > 0 {
      entries[index].status = "saved"; entries[index].itemId = itemId; entries[index].dreamId = dreamId
      entries[index].message = "Saved to Dreams. Your places are being organised."
    } else if httpStatus == 401 || httpStatus == 403 {
      entries[index].status = "sign_in"
      entries[index].message = "Your link is kept on this phone. Open Trotter to sign in again."
    } else if httpStatus == 0 || [408, 425, 429].contains(httpStatus) || httpStatus >= 500 || (200...299).contains(httpStatus) {
      entries[index].status = entries[index].attempts < 8 ? "queued" : "failed"
      entries[index].nextAttemptAt = now + min(30_000 * pow(2, Double(entries[index].attempts - 1)), 30 * 60_000)
      entries[index].message = "Kept on this phone. It will send when a connection is available."
    } else {
      entries[index].status = "failed"
      entries[index].message = "Kept on this phone. Open Dreams to try sending it again."
    }
  }
}
