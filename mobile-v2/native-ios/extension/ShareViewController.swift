import UIKit
import UniformTypeIdentifiers

/// No React startup and no extraction spinner. Keep the link first, show a small
/// paper receipt, then let iOS continue the upload after returning to Instagram.
final class ShareViewController: UIViewController {
  private let ink = UIColor(red: 49/255, green: 87/255, blue: 107/255, alpha: 1)
  private let muted = UIColor(red: 100/255, green: 118/255, blue: 128/255, alpha: 1)
  private let paper = UIColor(red: 250/255, green: 248/255, blue: 242/255, alpha: 1)
  private let heading = UILabel()
  private let detail = UILabel()
  private let done = UIButton(type: .system)
  private let io = DispatchQueue(label: "com.trotter.share.receipt")
  private let inputLock = NSLock()
  private var acceptingInput = true
  private var receivedText: [String] = []
  private var receiptId: String?
  private var poll: Timer?
  private var finished = false

  override func viewDidLoad() {
    super.viewDidLoad()
    view.backgroundColor = paper
    preferredContentSize = CGSize(width: 390, height: 240)
    buildReceipt()
    readSharedLink()
  }
  deinit { poll?.invalidate() }

  private func font(_ name: String, size: CGFloat, fallback: UIFont.TextStyle) -> UIFont {
    UIFontMetrics(forTextStyle: fallback).scaledFont(for: UIFont(name: name, size: size) ?? UIFont.systemFont(ofSize: size))
  }
  private func buildReceipt() {
    let brand = UILabel()
    brand.text = "Trotter"; brand.textColor = ink
    brand.font = font("Newsreader-Regular", size: 28, fallback: .title2)
    brand.adjustsFontForContentSizeCategory = true
    let mark = UIImageView(image: UIImage(systemName: "bookmark"))
    mark.tintColor = ink; mark.contentMode = .scaleAspectFit
    mark.isAccessibilityElement = false
    mark.widthAnchor.constraint(equalToConstant: 28).isActive = true
    let top = UIStackView(arrangedSubviews: [brand, UIView(), mark])
    top.axis = .horizontal; top.alignment = .center
    heading.text = "Keeping your link…"; heading.textColor = ink
    heading.font = font("Newsreader-Regular", size: 29, fallback: .title2)
    heading.numberOfLines = 0; heading.adjustsFontForContentSizeCategory = true
    heading.accessibilityTraits = .header
    detail.text = "Just a moment."; detail.textColor = muted
    detail.font = font("DMSans-Regular", size: 14, fallback: .body)
    detail.numberOfLines = 0; detail.adjustsFontForContentSizeCategory = true
    done.setTitle("Done", for: .normal); done.setTitleColor(ink, for: .normal)
    done.titleLabel?.font = font("DMSans-SemiBold", size: 15, fallback: .headline)
    done.titleLabel?.adjustsFontForContentSizeCategory = true
    done.contentHorizontalAlignment = .trailing
    done.heightAnchor.constraint(greaterThanOrEqualToConstant: 48).isActive = true
    done.addTarget(self, action: #selector(closeReceipt), for: .touchUpInside)
    done.isEnabled = false
    let rule = UIView(); rule.backgroundColor = ink.withAlphaComponent(0.15)
    rule.heightAnchor.constraint(equalToConstant: 1).isActive = true
    let stack = UIStackView(arrangedSubviews: [top, rule, heading, detail, done])
    stack.axis = .vertical; stack.spacing = 13
    stack.translatesAutoresizingMaskIntoConstraints = false
    let scroll = UIScrollView(); scroll.translatesAutoresizingMaskIntoConstraints = false
    view.addSubview(scroll); scroll.addSubview(stack)
    NSLayoutConstraint.activate([
      scroll.leadingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.leadingAnchor),
      scroll.trailingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.trailingAnchor),
      scroll.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor),
      scroll.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor),
      stack.leadingAnchor.constraint(equalTo: scroll.contentLayoutGuide.leadingAnchor, constant: 24),
      stack.trailingAnchor.constraint(equalTo: scroll.contentLayoutGuide.trailingAnchor, constant: -24),
      stack.topAnchor.constraint(equalTo: scroll.contentLayoutGuide.topAnchor, constant: 22),
      stack.bottomAnchor.constraint(equalTo: scroll.contentLayoutGuide.bottomAnchor, constant: -10),
      stack.widthAnchor.constraint(equalTo: scroll.frameLayoutGuide.widthAnchor, constant: -48)
    ])
  }

  private func readSharedLink() {
    let items = extensionContext?.inputItems.compactMap { $0 as? NSExtensionItem } ?? []
    for text in items.compactMap({ $0.attributedContentText?.string }) { receive(text) }
    for provider in items.flatMap({ $0.attachments ?? [] }).prefix(8) {
      // Prefer URL representations; captions can still be supplied separately.
      for type in [UTType.url.identifier, UTType.plainText.identifier] where provider.hasItemConformingToTypeIdentifier(type) {
        provider.loadItem(forTypeIdentifier: type, options: nil) { [weak self] value, _ in
          let text: String?
          if let url = value as? URL { text = url.absoluteString }
          else if let string = value as? String { text = string }
          else if let data = value as? Data { text = String(data: data, encoding: .utf8) }
          else { text = nil }
          if let text = text { self?.receive(text) }
        }
      }
    }
    // A host can fail to complete an item-provider callback. Offer a truthful exit.
    DispatchQueue.main.asyncAfter(deadline: .now() + 12) { [weak self] in
      guard let self = self, self.receiptId == nil, !self.finished else { return }
      self.heading.text = "The link hasn’t arrived"
      self.detail.text = "Return to Instagram and share the post or reel link again."
      self.done.isEnabled = true
    }
  }

  private func receive(_ text: String) {
    inputLock.lock()
    guard acceptingInput else { inputLock.unlock(); return }
    let bounded = String(text.prefix(60_000))
    if !receivedText.contains(bounded) { receivedText.append(bounded) }
    let snapshot = receivedText.joined(separator: "\n")
    inputLock.unlock()
    // Save the first valid URL immediately. A host's second representation can
    // hang forever; captions arriving later enrich the same idempotent capture.
    guard DreamShareInbox.canonicalURL(snapshot) != nil else { return }
    io.async {
      self.inputLock.lock()
      guard self.acceptingInput else { self.inputLock.unlock(); return }
      let result = Result { try DreamShareStore.shared.capture(snapshot) }
      self.inputLock.unlock()
      if case .success = result { DreamShareUploader.shared.flush() }
      DispatchQueue.main.async {
        guard !self.finished else { return }
        switch result {
        case .success(let receipt): self.receiptId = receipt.id; self.render(receipt)
        case .failure(let error):
          // A failed caption enrichment must not hide an already retained link.
          if self.receiptId == nil { self.showError(error) }
        }
      }
    }
  }

  private func refresh() {
    guard let id = receiptId, !finished else { return }
    io.async {
      if let receipt = try? DreamShareStore.shared.receipt(id) {
        DispatchQueue.main.async { if !self.finished { self.render(receipt) } }
      }
    }
  }
  private func render(_ receipt: DreamShareReceipt) {
    let previous = heading.text
    switch receipt.status {
    case "saved":
      heading.text = "Saved to Dreams"
      detail.text = "Your places are being organised."
      poll?.invalidate()
    case "sign_in":
      heading.text = "Link kept on this iPhone"
      detail.text = "Open Trotter and sign in to send it to Dreams."
      poll?.invalidate()
    case "failed":
      heading.text = "Link kept on this iPhone"
      detail.text = "Open Dreams to try sending it again."
      poll?.invalidate()
    default:
      heading.text = "Link kept for Dreams"
      detail.text = "You can return to Instagram. It will send when a connection is available."
      if poll == nil || poll?.isValid == false {
        poll = Timer.scheduledTimer(withTimeInterval: 0.6, repeats: true) { [weak self] _ in self?.refresh() }
      }
    }
    done.isEnabled = true
    if previous != heading.text { UIAccessibility.post(notification: .announcement, argument: heading.text) }
  }
  private func showError(_ error: Error) {
    guard !finished else { return }
    heading.text = "Couldn’t keep this link"
    detail.text = error.localizedDescription
    done.isEnabled = true
    UIAccessibility.post(notification: .announcement, argument: heading.text)
  }
  @objc private func closeReceipt() {
    guard !finished, done.isEnabled else { return }
    inputLock.lock(); acceptingInput = false; inputLock.unlock()
    finished = true; poll?.invalidate()
    extensionContext?.completeRequest(returningItems: nil)
  }
}
