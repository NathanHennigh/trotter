import Foundation
import React

@objc(TrotterDreamShare)
final class TrotterDreamShare: NSObject {
  private let bridgeId = UUID().uuidString
  private let queue = DispatchQueue(label: "com.trotter.dream-share.bridge")
  private var attachmentError: Error?
  override init() {
    super.init()
    do { try DreamShareStore.shared.attachBridge(bridgeId) }
    catch { attachmentError = error }
  }
  @objc static func requiresMainQueueSetup() -> Bool { false }

  private func run(_ code: String, resolve: @escaping RCTPromiseResolveBlock,
    reject: @escaping RCTPromiseRejectBlock, action: @escaping () throws -> Any?) {
    queue.async {
      do {
        if let error = self.attachmentError { throw error }
        resolve(try action())
      } catch { reject(code, error.localizedDescription, error) }
    }
  }

  @objc(invalidateSession:resolver:rejecter:)
  func invalidateSession(_ revision: Int, resolver: @escaping RCTPromiseResolveBlock, rejecter: @escaping RCTPromiseRejectBlock) {
    queue.async {
      do {
        if let error = self.attachmentError { throw error }
        if try DreamShareStore.shared.invalidate(revision: revision, bridgeId: self.bridgeId) {
          DreamShareUploader.shared.cancelActiveUploads { resolver(nil) }
        } else { resolver(nil) }
      } catch { rejecter("SHARE_SIGN_OUT", error.localizedDescription, error) }
    }
  }
  @objc(configureSession:ownerId:token:revision:resolver:rejecter:)
  func configureSession(_ apiBaseUrl: String, ownerId: Int, token: String, revision: Int,
    resolver: @escaping RCTPromiseResolveBlock, rejecter: @escaping RCTPromiseRejectBlock) {
    run("SHARE_SIGN_IN", resolve: resolver, reject: rejecter) {
      try DreamShareStore.shared.configure(apiBaseUrl: apiBaseUrl, ownerId: ownerId, token: token, revision: revision, bridgeId: self.bridgeId)
      DreamShareUploader.shared.flush()
      return nil
    }
  }
  @objc(listReceipts:rejecter:)
  func listReceipts(_ resolver: @escaping RCTPromiseResolveBlock, rejecter: @escaping RCTPromiseRejectBlock) {
    run("SHARE_RECEIPTS", resolve: resolver, reject: rejecter) { try DreamShareStore.shared.visible().map { $0.bridgeValue } }
  }
  @objc(flush:rejecter:)
  func flush(_ resolver: @escaping RCTPromiseResolveBlock, rejecter: @escaping RCTPromiseRejectBlock) {
    run("SHARE_RETRY", resolve: resolver, reject: rejecter) { DreamShareUploader.shared.flush(); return nil }
  }
  @objc(retry:resolver:rejecter:)
  func retry(_ id: String, resolver: @escaping RCTPromiseResolveBlock, rejecter: @escaping RCTPromiseRejectBlock) {
    run("SHARE_RETRY", resolve: resolver, reject: rejecter) {
      try DreamShareStore.shared.retry(id); DreamShareUploader.shared.flush(); return nil
    }
  }
  @objc(acknowledge:resolver:rejecter:)
  func acknowledge(_ id: String, resolver: @escaping RCTPromiseResolveBlock, rejecter: @escaping RCTPromiseRejectBlock) {
    run("SHARE_RECEIPT", resolve: resolver, reject: rejecter) { try DreamShareStore.shared.acknowledge(id); return nil }
  }
  @objc(forgetAccount:ownerId:resolver:rejecter:)
  func forgetAccount(_ apiBaseUrl: String, ownerId: Int, resolver: @escaping RCTPromiseResolveBlock, rejecter: @escaping RCTPromiseRejectBlock) {
    queue.async {
      do {
        if let error = self.attachmentError { throw error }
        let removed = try DreamShareStore.shared.forgetAccount(apiBaseUrl: apiBaseUrl, ownerId: ownerId)
        DreamShareUploader.shared.forgetUploads(receiptIDs: removed.0, sessionGeneration: removed.1) { error in
          if let error = error { rejecter("SHARE_ERASURE", "The account was deleted, but saved links could not be cleared from this iPhone.", error) }
          else { resolver(nil) }
        }
      } catch { rejecter("SHARE_ERASURE", "The account was deleted, but saved links could not be cleared from this iPhone.", error) }
    }
  }
}
