import Foundation

struct JarvisConfigContract {
    let version: Int
    let defaults: [String: Any]
    let fields: [String: [String: Any]]
    let backends: [String: [String: Any]]
    let uiOptions: [String: [Any]]

    static let empty = JarvisConfigContract(
        version: 1,
        defaults: [:],
        fields: [:],
        backends: [:],
        uiOptions: [:]
    )

    static func fromJSON(_ text: String) throws -> JarvisConfigContract {
        guard let data = text.data(using: .utf8) else {
            throw JarvisConfigContractError.invalidEncoding
        }
        guard let root = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw JarvisConfigContractError.invalidRoot
        }
        let version = root["version"] as? Int ?? 0
        guard version == 1 else {
            throw JarvisConfigContractError.unsupportedVersion(version)
        }
        return JarvisConfigContract(
            version: version,
            defaults: root["defaults"] as? [String: Any] ?? [:],
            fields: root["fields"] as? [String: [String: Any]] ?? [:],
            backends: root["backends"] as? [String: [String: Any]] ?? [:],
            uiOptions: root["ui_options"] as? [String: [Any]] ?? [:]
        )
    }

    func stringDefault(_ key: String) -> String? {
        guard let value = defaults[key], !(value is NSNull) else {
            return nil
        }
        return value as? String ?? String(describing: value)
    }

    func stringOptions(_ key: String, fallback: [String] = []) -> [String] {
        let values = optionValues(key)
        let result = values.compactMap { value -> String? in
            guard !(value is NSNull) else { return nil }
            return value as? String ?? String(describing: value)
        }
        return result.isEmpty ? fallback : result
    }

    func intOptions(_ key: String, fallback: [Int] = []) -> [Int] {
        let result = optionValues(key).compactMap { value -> Int? in
            if let number = value as? Int { return number }
            if let number = value as? Double { return Int(number) }
            if let text = value as? String { return Int(text) }
            return nil
        }
        return result.isEmpty ? fallback : result
    }

    func doubleOptions(_ key: String, fallback: [Double] = []) -> [Double] {
        let result = optionValues(key).compactMap { value -> Double? in
            if let number = value as? Double { return number }
            if let number = value as? Int { return Double(number) }
            if let text = value as? String { return Double(text) }
            return nil
        }
        return result.isEmpty ? fallback : result
    }

    private func optionValues(_ key: String) -> [Any] {
        if let values = uiOptions[key], !values.isEmpty {
            return values
        }
        return fields[key]?["values"] as? [Any] ?? []
    }
}

enum JarvisConfigContractError: LocalizedError {
    case invalidEncoding
    case invalidRoot
    case unsupportedVersion(Int)

    var errorDescription: String? {
        switch self {
        case .invalidEncoding:
            return "The config contract is not valid UTF-8."
        case .invalidRoot:
            return "The config contract must be a JSON object."
        case .unsupportedVersion(let version):
            return "Unsupported config contract version: \(version)."
        }
    }
}
