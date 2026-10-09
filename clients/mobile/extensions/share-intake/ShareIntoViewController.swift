import UIKit
import UniformTypeIdentifiers

// No network, credentials, UIApplication.open or host-app responder-chain calls.
// Only an explicit Save publishes a completed, immutable inbox directory.
final class ShareIntoViewController: UIViewController {
  private let maxFile = 15 * 1024 * 1024
  private let maxTotal = 30 * 1024 * 1024
  private let message = UILabel()
  private let saveButton = UIButton(type: .system)
  private let cancelButton = UIButton(type: .system)
  private var work: Task<Void, Never>?
  private var committed = false

  override func viewDidLoad() {
    super.viewDidLoad()
    view.backgroundColor = .systemBackground
    let title = UILabel()
    title.text = "保存到 Pajio"
    title.font = .preferredFont(forTextStyle: .title2)
    title.adjustsFontForContentSizeCategory = true
    message.text = "内容先保存在这台手机。打开 Pajio 后，选择身份，再确认导入或带入聊天。"
    message.numberOfLines = 0
    message.font = .preferredFont(forTextStyle: .body)
    message.adjustsFontForContentSizeCategory = true
    saveButton.setTitle("保存在手机", for: .normal)
    saveButton.configuration = .filled()
    saveButton.addTarget(self, action: #selector(save), for: .touchUpInside)
    cancelButton.setTitle("取消", for: .normal)
    cancelButton.addTarget(self, action: #selector(cancel), for: .touchUpInside)
    let stack = UIStackView(arrangedSubviews: [title, message, saveButton, cancelButton])
    stack.axis = .vertical; stack.spacing = 24
    stack.translatesAutoresizingMaskIntoConstraints = false
    view.addSubview(stack)
    NSLayoutConstraint.activate([
      stack.leadingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.leadingAnchor, constant: 28),
      stack.trailingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.trailingAnchor, constant: -28),
      stack.centerYAnchor.constraint(equalTo: view.safeAreaLayoutGuide.centerYAnchor),
      saveButton.heightAnchor.constraint(greaterThanOrEqualToConstant: 48),
      cancelButton.heightAnchor.constraint(greaterThanOrEqualToConstant: 44)
    ])
  }

  @objc private func cancel() {
    work?.cancel()
    extensionContext?.cancelRequest(withError: NSError(domain: NSCocoaErrorDomain, code: NSUserCancelledError))
  }

  @objc private func save() {
    if committed { extensionContext?.completeRequest(returningItems: nil); return }
    guard work == nil else { return }
    saveButton.isEnabled = false
    message.text = "正在保存在手机…"
    work = Task { @MainActor in
      do {
        try await persist()
        committed = true
        message.text = "已保存在手机。回到 Pajio，即可预览和选择要做的事。"
        saveButton.setTitle("完成", for: .normal)
        cancelButton.isHidden = true
      } catch {
        message.text = (error as? IntakeError)?.message ?? "这次没有保存成功，请重新分享。"
        cancelButton.isEnabled = true
      }
      saveButton.isEnabled = true; work = nil
    }
  }

  private struct IntakeError: Error { let message: String }
  private func fail(_ text: String) -> IntakeError { IntakeError(message: text) }

  private func persist() async throws {
    let fm = FileManager.default
    guard let group = Bundle.main.object(forInfoDictionaryKey: "AppGroupId") as? String,
          let container = fm.containerURL(forSecurityApplicationGroupIdentifier: group) else {
      throw fail("分享空间尚未就绪，请打开新版 Pajio 后再试。")
    }
    let providers = (extensionContext?.inputItems as? [NSExtensionItem] ?? []).flatMap { $0.attachments ?? [] }
    guard !providers.isEmpty, providers.count <= 5 else { throw fail("一次最多分享 4 个文件和一段文字。") }
    let inbox = container.appendingPathComponent("pajio-share-inbox", isDirectory: true)
    try fm.createDirectory(at: inbox, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700, .protectionKey: FileProtectionType.completeUntilFirstUserAuthentication])
    let existing = try fm.contentsOfDirectory(at: inbox, includingPropertiesForKeys: [.creationDateKey])
    // Only extension-owned abandoned staging directories, never ready content.
    // A killed extension may leave a partial directory; cap live staging too.
    var occupied = 0
    for entry in existing {
      let name = entry.lastPathComponent
      if name.hasPrefix("."), UUID(uuidString: String(name.dropFirst())) != nil,
         let created = try entry.resourceValues(forKeys: [.creationDateKey]).creationDate,
         created.timeIntervalSinceNow < -86400 {
        try fm.removeItem(at: entry)
      } else { occupied += 1 }
    }
    guard occupied < 8 else {
      throw fail("有 8 份分享等待处理，请先打开 Pajio 整理后再分享。")
    }
    let id = UUID().uuidString.lowercased()
    let staging = inbox.appendingPathComponent(".\(id)", isDirectory: true)
    try fm.createDirectory(at: staging, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
    defer { try? fm.removeItem(at: staging) }
    var files: [[String: Any]] = []
    var texts: [String] = []
    var total = 0
    for provider in providers {
      try Task.checkCancellation()
      let binaryTypes: [(UTType, String, String)] = [(.jpeg, "image/jpeg", "jpg"), (.png, "image/png", "png"), (.gif, "image/gif", "gif"), (.heic, "image/heic", "heic"), (UTType("org.webmproject.webp") ?? .image, "image/webp", "webp"), (.pdf, "application/pdf", "pdf"), (.zip, "application/zip", "zip")]
      if let kind = binaryTypes.first(where: { provider.hasItemConformingToTypeIdentifier($0.0.identifier) }) {
        guard files.count < 4 else { throw fail("一次最多分享 4 个文件。") }
        let filename = "\(files.count).\(kind.2)"
        let target = staging.appendingPathComponent(filename)
        let limit = min(maxFile, maxTotal - total)
        let size = try await copyFile(provider, type: kind.0.identifier, destination: target, limit: limit)
        total += size
        let suggested = provider.suggestedName?.replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "\\", with: "_") ?? "分享文件.\(kind.2)"
        files.append(["path": filename, "name": String(suggested.prefix(160)), "mime": kind.1, "size": size])
      } else if provider.hasItemConformingToTypeIdentifier(UTType.url.identifier) {
        let value = try await load(provider, type: UTType.url.identifier)
        guard let url = value as? URL, ["https", "http"].contains(url.scheme?.lowercased() ?? ""), url.user == nil, url.password == nil, url.host != nil else {
          throw fail("这个链接类型暂不支持，请分享网页链接、文字、图片或 PDF。")
        }
        texts.append(url.absoluteString)
      } else if provider.hasItemConformingToTypeIdentifier(UTType.plainText.identifier) {
        let filename = "\(files.count).txt"
        let value = try await loadPlainText(provider, destination: staging.appendingPathComponent(filename), limit: min(maxFile, maxTotal - total))
        switch value {
        case .text(let text): texts.append(text)
        case .file(let size, let name):
          guard files.count < 4 else { throw fail("一次最多分享 4 个文件。") }
          total += size
          files.append(["path": filename, "name": name, "mime": "text/plain", "size": size])
        }
      } else { throw fail("支持网页链接、文字、图片、PDF 和聊天 ZIP；请换一种格式。") }
      guard texts.joined(separator: "\n\n").utf16.count <= 12000 else { throw fail("分享文字最多 12000 字，请缩短后重试。") }
    }
    guard !files.isEmpty || !texts.joined().trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { throw fail("这份分享里没有可保存的内容。") }
    let manifest: [String: Any] = ["version": 1, "id": id, "createdAt": ISO8601DateFormatter().string(from: Date()), "text": texts.joined(separator: "\n\n"), "files": files]
    let data = try JSONSerialization.data(withJSONObject: manifest)
    try data.write(to: staging.appendingPathComponent("manifest.json"), options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
    var excluded = staging; var values = URLResourceValues(); values.isExcludedFromBackup = true
    try excluded.setResourceValues(values)
    try Task.checkCancellation()
    try fm.moveItem(at: staging, to: inbox.appendingPathComponent(id, isDirectory: true))
  }

  private enum PlainResult { case text(String); case file(Int, String) }
  private func loadPlainText(_ provider: NSItemProvider, destination: URL, limit: Int) async throws -> PlainResult {
    try await withCheckedThrowingContinuation { continuation in
      provider.loadItem(forTypeIdentifier: UTType.plainText.identifier) { item, error in
        do {
          if let error { throw error }
          if let text = item as? String { continuation.resume(returning: .text(text)) }
          else if let url = item as? URL, url.isFileURL {
            let size = try Self.copyBounded(url, to: destination, limit: limit)
            continuation.resume(returning: .file(size, String(url.lastPathComponent.prefix(160))))
          } else { throw IntakeError(message: "暂时读不到分享的文字，请重新分享。") }
        } catch { continuation.resume(throwing: error) }
      }
    }
  }

  private func load(_ provider: NSItemProvider, type: String) async throws -> NSSecureCoding {
    try await withCheckedThrowingContinuation { continuation in
      provider.loadItem(forTypeIdentifier: type) { item, error in
        if let error { continuation.resume(throwing: error) }
        else if let item { continuation.resume(returning: item) }
        else { continuation.resume(throwing: IntakeError(message: "暂时读不到分享内容。")) }
      }
    }
  }

  private func copyFile(_ provider: NSItemProvider, type: String, destination: URL, limit: Int) async throws -> Int {
    try await withCheckedThrowingContinuation { continuation in
      provider.loadFileRepresentation(forTypeIdentifier: type) { url, error in
        do {
          if let error { throw error }
          guard let url else { throw IntakeError(message: "文件暂时无法读取。") }
          // Provider temporary URLs are valid only inside this callback.
          continuation.resume(returning: try Self.copyBounded(url, to: destination, limit: limit))
        } catch { continuation.resume(throwing: error) }
      }
    }
  }

  private static func copyBounded(_ source: URL, to destination: URL, limit: Int) throws -> Int {
    let values = try source.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey])
    guard values.isRegularFile == true, values.isSymbolicLink != true, (values.fileSize ?? 0) <= limit,
          let input = InputStream(url: source), let output = OutputStream(url: destination, append: false) else {
      throw IntakeError(message: "每个文件最多 15 MB，总计最多 30 MB；文件夹暂不支持。")
    }
    input.open(); output.open()
    defer { input.close(); output.close() }
    var buffer = [UInt8](repeating: 0, count: 65536)
    var total = 0
    while true {
      let read = input.read(&buffer, maxLength: buffer.count)
      if read == 0 { break }
      guard read > 0 else { throw IntakeError(message: "读取文件失败，请重新分享。") }
      total += read
      guard total <= limit else { throw IntakeError(message: "每个文件最多 15 MB，总计最多 30 MB。") }
      var offset = 0
      try buffer.withUnsafeBufferPointer { bytes in
        while offset < read {
          let written = output.write(bytes.baseAddress!.advanced(by: offset), maxLength: read - offset)
          guard written > 0 else { throw IntakeError(message: "手机存储空间不足或暂不可写。") }
          offset += written
        }
      }
    }
    guard total > 0 else { throw IntakeError(message: "空文件无法导入。") }
    try FileManager.default.setAttributes([.posixPermissions: 0o600, .protectionKey: FileProtectionType.completeUntilFirstUserAuthentication], ofItemAtPath: destination.path)
    return total
  }
}
