// Thin adapter to Apple's existing Vision text recognition; no UI automation.
import Foundation
import Vision
let input = URL(fileURLWithPath: CommandLine.arguments[1])
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = ["zh-Hans", "en-US"]
request.usesLanguageCorrection = true
do {
    try VNImageRequestHandler(url: input).perform([request])
    let lines = (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }
    let result = try JSONSerialization.data(withJSONObject: ["text": lines.joined(separator: "\n")])
    print(String(data: result, encoding: .utf8)!)
} catch {
    print("{\"error\":\"图片文字暂时没有读出来，原图已保存。\"}")
    exit(1)
}
