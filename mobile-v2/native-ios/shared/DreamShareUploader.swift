import Foundation

/// File-backed background uploads survive the extension being dismissed. The app
/// reconnects to extension sessions only when iOS explicitly hands them to it.
final class DreamShareUploader: NSObject, URLSessionDataDelegate, URLSessionTaskDelegate {
  static let shared = DreamShareUploader()
  private let work = DispatchQueue(label: "com.trotter.dream-share.upload")
  private let delegateQueue: OperationQueue = {
    let queue = OperationQueue(); queue.maxConcurrentOperationCount = 1; return queue
  }()
  private var sessions: [String: URLSession] = [:]
  private var responses: [String: Data] = [:]
  private var completions: [String: () -> Void] = [:]
  private var finishing = Set<String>()

  static var appSessionId: String { TrotterShareConfiguration.bundleIdentifier + ".dreamshare.app" }
  static var extensionSessionId: String { TrotterShareConfiguration.bundleIdentifier + ".dreamshare.extension" }
  static var ownSessionId: String { Bundle.main.bundleURL.pathExtension == "appex" ? extensionSessionId : appSessionId }

  private func session(_ identifier: String) -> URLSession {
    if let session = sessions[identifier] { return session }
    let config = URLSessionConfiguration.background(withIdentifier: identifier)
    config.sharedContainerIdentifier = TrotterShareConfiguration.appGroup
    config.isDiscretionary = false
    config.waitsForConnectivity = true
    config.timeoutIntervalForRequest = 30
    config.timeoutIntervalForResource = 120
    config.httpMaximumConnectionsPerHost = 3
    config.httpCookieStorage = nil; config.httpShouldSetCookies = false
    let value = URLSession(configuration: config, delegate: self, delegateQueue: delegateQueue)
    sessions[identifier] = value
    return value
  }

  func flush() { work.async { self.enqueuePending() } }

  private func enqueuePending() {
    try? DreamShareStore.shared.cleanErasedPayloads()
    guard let claim = try? DreamShareStore.shared.claim() else { return }
    let (credential, entries) = claim
    for receipt in entries {
      do {
        guard try DreamShareStore.shared.session() == credential else { return }
        let folder = try DreamShareStore.shared.directory()
        let file = folder.appendingPathComponent("\(receipt.id)-\(receipt.generation).json")
        let body = try JSONSerialization.data(withJSONObject: ["source_url": receipt.sourceUrl,
          "source_platform": "instagram", "shared_text": receipt.sharedText])
        try body.write(to: file, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
        guard let url = URL(string: credential.owner.apiBaseUrl + "/dreams/share") else { throw DreamShareError.invalidSession }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("Bearer \(credential.token)", forHTTPHeaderField: "Authorization")
        let task = session(Self.ownSessionId).uploadTask(with: request, fromFile: file)
        task.taskDescription = "\(receipt.id)|\(receipt.generation)|\(credential.generation)"
        if receipt.nextAttemptAt > DreamShareStore.now {
          task.earliestBeginDate = Date(timeIntervalSince1970: receipt.nextAttemptAt / 1000)
        }
        task.resume()
      } catch {
        try? DreamShareStore.shared.complete(sessionGeneration: credential.generation, id: receipt.id,
          generation: receipt.generation, httpStatus: 0, itemId: nil, dreamId: nil)
      }
    }
  }

  /// Signing out happens in the containing app, after its persisted tombstone.
  /// Reconnect to the extension's suspended session to cancel queued requests too.
  func cancelActiveUploads(completion: @escaping () -> Void) {
    cancelUploads(matching: { _ in true }, completion: completion)
  }

  func forgetUploads(receiptIDs: Set<String>, sessionGeneration: String?, completion: @escaping (Error?) -> Void) {
    cancelUploads(matching: { task in
      let parts = task.taskDescription?.split(separator: "|").map(String.init) ?? []
      guard parts.count == 3 else { return false }
      return receiptIDs.contains(parts[0]) || (sessionGeneration != nil && parts[2] == sessionGeneration)
    }) {
      do { try DreamShareStore.shared.cleanErasedPayloads(); completion(nil) }
      catch { completion(error) }
    }
  }

  private func cancelUploads(matching shouldCancel: @escaping (URLSessionTask) -> Bool, completion: @escaping () -> Void) {
    work.async {
      let group = DispatchGroup()
      let identifiers = Bundle.main.bundleURL.pathExtension == "appex" ? [Self.ownSessionId] : [Self.appSessionId, Self.extensionSessionId]
      for identifier in identifiers {
        group.enter()
        self.session(identifier).getAllTasks { tasks in
          tasks.filter(shouldCancel).forEach { $0.cancel() }
          group.leave()
        }
      }
      group.notify(queue: self.work) {
        if Self.ownSessionId != Self.extensionSessionId {
          self.sessions.removeValue(forKey: Self.extensionSessionId)?.finishTasksAndInvalidate()
        }
        completion()
      }
    }
  }

  func handleBackgroundEvents(identifier: String, completion: @escaping () -> Void) -> Bool {
    guard [Self.appSessionId, Self.extensionSessionId].contains(identifier) else { return false }
    work.async {
      self.completions[identifier] = completion
      _ = self.session(identifier)
      if self.finishing.remove(identifier) != nil { self.finish(identifier) }
    }
    return true
  }

  private func finish(_ identifier: String) {
    guard let completion = completions.removeValue(forKey: identifier) else { finishing.insert(identifier); return }
    // Hand the extension-owned session back after processing its events.
    if identifier != Self.ownSessionId { sessions.removeValue(forKey: identifier)?.finishTasksAndInvalidate() }
    DispatchQueue.main.async(execute: completion)
  }

  func urlSessionDidFinishEvents(forBackgroundURLSession session: URLSession) {
    guard let identifier = session.configuration.identifier else { return }
    work.async { self.finish(identifier) }
  }

  private func responseKey(_ session: URLSession, _ task: URLSessionTask) -> String {
    "\(session.configuration.identifier ?? "")/\(task.taskIdentifier)"
  }
  func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
    let key = responseKey(session, dataTask)
    // Only a tiny JSON receipt is expected. Do not let an error page exhaust the extension.
    if (responses[key]?.count ?? 0) + data.count > 128 * 1024 { dataTask.cancel(); return }
    responses[key, default: Data()].append(data)
  }
  func urlSession(_ session: URLSession, didReceive challenge: URLAuthenticationChallenge,
    completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
    // Background URLSession follows redirects without consulting the redirect
    // delegate. Only the configured HTTPS API host may pass authentication.
    guard let credential = try? DreamShareStore.shared.session(),
      let expected = URL(string: credential.owner.apiBaseUrl)?.host,
      challenge.protectionSpace.host.caseInsensitiveCompare(expected) == .orderedSame,
      challenge.protectionSpace.protocol == "https" else {
      completionHandler(.cancelAuthenticationChallenge, nil); return
    }
    completionHandler(.performDefaultHandling, nil)
  }
  func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
    let data = responses.removeValue(forKey: responseKey(session, task)) ?? Data()
    let parts = task.taskDescription?.split(separator: "|").map(String.init) ?? []
    guard parts.count == 3, UUID(uuidString: parts[0]) != nil, let generation = Int(parts[1]), UUID(uuidString: parts[2]) != nil else { return }
    let status = error == nil ? ((task.response as? HTTPURLResponse)?.statusCode ?? 0) : 0
    let receipt = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
    work.async {
      try? DreamShareStore.shared.complete(sessionGeneration: parts[2], id: parts[0], generation: generation,
        httpStatus: status, itemId: receipt?["dream_item_id"] as? Int, dreamId: receipt?["dream_id"] as? Int)
      if status == 401 || status == 403 { self.cancelActiveUploads(completion: {}) }
      if let folder = try? DreamShareStore.shared.directory() {
        try? FileManager.default.removeItem(at: folder.appendingPathComponent("\(parts[0])-\(generation).json"))
      }
      self.enqueuePending()
    }
  }
}
