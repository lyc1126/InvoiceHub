import CryptoKit
import Foundation

enum SparkleVerificationError: LocalizedError {
    case invalidArguments(String)
    case invalidBase64(String)
    case wrongLength(String, Int, Int)
    case missingPublicKey
    case publicKeyMismatch
    case invalidSignature

    var errorDescription: String? {
        switch self {
        case let .invalidArguments(message): return message
        case let .invalidBase64(label): return "\(label) is not strict Base64."
        case let .wrongLength(label, expected, actual): return "\(label) must contain \(expected) bytes, got \(actual)."
        case .missingPublicKey: return "The signed update app does not contain SUPublicEDKey."
        case .publicKeyMismatch: return "The signed update app public key differs from the trusted public key."
        case .invalidSignature: return "Sparkle Ed25519 signature does not verify the update ZIP bytes."
        }
    }
}

struct Arguments {
    let archive: String
    let signatureFile: String
    let trustedPublicKey: String
    let appBundle: String

    init(_ values: [String: String]) throws {
        let required = ["--archive", "--signature-file", "--trusted-public-key", "--app"]
        guard values.count == required.count,
              required.allSatisfy({ values[$0]?.isEmpty == false }) else {
            throw SparkleVerificationError.invalidArguments(
                "Usage: verify_sparkle_update.swift --archive <zip> --signature-file <file> --trusted-public-key <base64> --app <InvoiceHub.app>"
            )
        }
        archive = values["--archive"]!
        signatureFile = values["--signature-file"]!
        trustedPublicKey = values["--trusted-public-key"]!
        appBundle = values["--app"]!
    }

    static func parse() throws -> Arguments {
        let raw = Array(CommandLine.arguments.dropFirst())
        guard raw.count.isMultiple(of: 2) else {
            throw SparkleVerificationError.invalidArguments("Every verifier option must have one value.")
        }
        var values: [String: String] = [:]
        var index = 0
        while index < raw.count {
            let option = raw[index]
            guard option.hasPrefix("--"), values[option] == nil else {
                throw SparkleVerificationError.invalidArguments("Unknown or duplicate verifier option: \(option)")
            }
            values[option] = raw[index + 1]
            index += 2
        }
        return try Arguments(values)
    }
}

func strictBase64(_ value: String, label: String, expectedLength: Int) throws -> Data {
    guard let data = Data(base64Encoded: value, options: []) else {
        throw SparkleVerificationError.invalidBase64(label)
    }
    guard data.count == expectedLength else {
        throw SparkleVerificationError.wrongLength(label, expectedLength, data.count)
    }
    return data
}

func sparkleSignature(from signatureFile: String) throws -> String {
    let text = try String(contentsOfFile: signatureFile, encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines)
    let expression = try NSRegularExpression(pattern: #"(?:sparkle:)?edSignature=\"([^\"]+)\""#)
    let range = NSRange(text.startIndex..., in: text)
    if let match = expression.firstMatch(in: text, range: range),
       let signatureRange = Range(match.range(at: 1), in: text) {
        return String(text[signatureRange])
    }
    return text
}

func signedAppPublicKey(appBundle: String) throws -> String {
    let plistURL = URL(fileURLWithPath: appBundle)
        .appendingPathComponent("Contents")
        .appendingPathComponent("Info.plist")
    let plistData = try Data(contentsOf: plistURL)
    let plist = try PropertyListSerialization.propertyList(from: plistData, options: [], format: nil)
    guard let dictionary = plist as? [String: Any],
          let key = dictionary["SUPublicEDKey"] as? String,
          !key.isEmpty else {
        throw SparkleVerificationError.missingPublicKey
    }
    return key
}

do {
    let arguments = try Arguments.parse()
    let trustedKey = try strictBase64(arguments.trustedPublicKey, label: "Trusted Sparkle public key", expectedLength: 32)
    let appKey = try strictBase64(try signedAppPublicKey(appBundle: arguments.appBundle), label: "Signed app SUPublicEDKey", expectedLength: 32)
    guard appKey == trustedKey else {
        throw SparkleVerificationError.publicKeyMismatch
    }
    let signature = try strictBase64(try sparkleSignature(from: arguments.signatureFile), label: "Sparkle Ed25519 signature", expectedLength: 64)
    let archive = try Data(contentsOf: URL(fileURLWithPath: arguments.archive))
    let publicKey = try Curve25519.Signing.PublicKey(rawRepresentation: trustedKey)
    guard publicKey.isValidSignature(signature, for: archive) else {
        throw SparkleVerificationError.invalidSignature
    }
} catch {
    fputs("Sparkle update verification failed: \(error.localizedDescription)\n", stderr)
    exit(1)
}
