import AppKit
import Foundation
import Vision

struct OCRItem: Codable {
    let path: String
    let text: String
}

struct OCRResult: Codable {
    let items: [OCRItem]
}

func recognizeText(at path: String) -> String {
    let url = URL(fileURLWithPath: path)
    guard let image = NSImage(contentsOf: url) else {
        return ""
    }

    var rect = NSRect(origin: .zero, size: image.size)
    guard let cgImage = image.cgImage(forProposedRect: &rect, context: nil, hints: nil) else {
        return ""
    }

    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = true
    request.recognitionLanguages = ["zh-Hans", "en-US"]

    let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])

    do {
        try handler.perform([request])
        let observations = (request.results as? [VNRecognizedTextObservation]) ?? []
        let lines = observations.compactMap { observation in
            observation.topCandidates(1).first?.string.trimmingCharacters(in: .whitespacesAndNewlines)
        }.filter { !$0.isEmpty }
        return lines.joined(separator: "\n")
    } catch {
        return ""
    }
}

let imagePaths = Array(CommandLine.arguments.dropFirst())
let items = imagePaths.map { path in
    OCRItem(path: path, text: recognizeText(at: path))
}

let result = OCRResult(items: items)
let encoder = JSONEncoder()
encoder.outputFormatting = [.prettyPrinted, .withoutEscapingSlashes]

if let data = try? encoder.encode(result),
   let output = String(data: data, encoding: .utf8) {
    FileHandle.standardOutput.write(output.data(using: .utf8)!)
}
