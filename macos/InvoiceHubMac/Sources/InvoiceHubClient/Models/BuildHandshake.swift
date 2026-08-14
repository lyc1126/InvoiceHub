import Foundation

public struct InvoiceHubBuildManifest: Codable, Equatable {
    public let buildID: String
    public let apiContractVersion: String
    public let bookkeepingProtocolVersion: String
    public let capabilities: [String]
    public let sourceCommit: String
    public let builtAt: String

    enum CodingKeys: String, CodingKey {
        case buildID = "build_id"
        case apiContractVersion = "api_contract_version"
        case bookkeepingProtocolVersion = "bookkeeping_protocol_version"
        case capabilities
        case sourceCommit = "source_commit"
        case builtAt = "built_at"
    }

    public static func load(
        from coreRoot: URL,
        releaseMode: Bool = Bundle.main.object(forInfoDictionaryKey: "InvoiceHubReleaseMode") as? Bool == true
    ) throws -> InvoiceHubBuildManifest {
        let url = coreRoot.appendingPathComponent("invoice-hub-build.json")
        guard FileManager.default.fileExists(atPath: url.path) else {
            throw BuildManifestError.missing(url.path)
        }
        do {
            let manifest = try JSONDecoder().decode(InvoiceHubBuildManifest.self, from: Data(contentsOf: url))
            guard
                !manifest.buildID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                !manifest.apiContractVersion.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                !manifest.bookkeepingProtocolVersion.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                !manifest.capabilities.isEmpty,
                manifest.capabilities.allSatisfy({ !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }),
                (!releaseMode || manifest.buildID.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil),
                (!releaseMode || manifest.sourceCommit.range(of: "^[0-9a-f]{40}$", options: .regularExpression) != nil),
                (!releaseMode || !manifest.builtAt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            else {
                throw BuildManifestError.invalid(url.path)
            }
            return manifest
        } catch let error as BuildManifestError {
            throw error
        } catch {
            throw BuildManifestError.invalid(url.path)
        }
    }
}

public enum BuildManifestError: LocalizedError, Equatable {
    case missing(String)
    case invalid(String)

    public var errorDescription: String? {
        switch self {
        case .missing(let path):
            return "App 缺少构建清单，禁止连接未知后端。清单路径: \(path)"
        case .invalid(let path):
            return "App 构建清单无效，禁止连接未知后端。清单路径: \(path)"
        }
    }
}

public struct InvoiceHubPackageManifest: Codable, Equatable {
    public let schemaVersion: Int
    public let packageID: String
    public let productVersion: String
    public let platform: String
    public let architecture: String
    public let packageType: String
    public let pythonVersion: String
    public let dependencyLockSHA256: String
    public let updateChannel: String
    public let updateFeedURL: String
    public let allowedUpdateHosts: [String]
    public let coreBuildID: String
    public let sourceCommit: String

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case packageID = "package_id"
        case productVersion = "product_version"
        case platform
        case architecture
        case packageType = "package_type"
        case pythonVersion = "python_version"
        case dependencyLockSHA256 = "dependency_lock_sha256"
        case updateChannel = "update_channel"
        case updateFeedURL = "update_feed_url"
        case allowedUpdateHosts = "allowed_update_hosts"
        case coreBuildID = "core_build_id"
        case sourceCommit = "source_commit"
    }

    public static func load(
        from coreRoot: URL,
        releaseMode: Bool = Bundle.main.object(forInfoDictionaryKey: "InvoiceHubReleaseMode") as? Bool == true
    ) throws -> InvoiceHubPackageManifest {
        let url = coreRoot.appendingPathComponent("invoice-hub-package.json")
        guard FileManager.default.fileExists(atPath: url.path) else {
            throw PackageManifestError.missing(url.path)
        }
        do {
            let manifest = try JSONDecoder().decode(InvoiceHubPackageManifest.self, from: Data(contentsOf: url))
            guard
                manifest.schemaVersion == 1,
                manifest.packageID == "com.invoicehub.macos.arm64.dmg",
                manifest.productVersion == "0.3.0-alpha.1",
                manifest.platform == "macos",
                manifest.architecture == "arm64",
                manifest.packageType == "dmg",
                (releaseMode
                    ? manifest.pythonVersion == "3.14.6"
                    : manifest.pythonVersion.range(of: "^3\\.14\\.\\d+$", options: .regularExpression) != nil),
                manifest.dependencyLockSHA256.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil,
                manifest.updateChannel == "beta",
                manifest.updateFeedURL == "https://lyc1126.github.io/InvoiceHub/updates/alpha/latest.json",
                manifest.allowedUpdateHosts == [
                    "github.com",
                    "lyc1126.github.io",
                    "objects.githubusercontent.com",
                    "release-assets.githubusercontent.com"
                ],
                manifest.coreBuildID.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil,
                manifest.sourceCommit.range(of: "^[0-9a-f]{40}$", options: .regularExpression) != nil
            else {
                throw PackageManifestError.invalid(url.path)
            }
            return manifest
        } catch let error as PackageManifestError {
            throw error
        } catch {
            throw PackageManifestError.invalid(url.path)
        }
    }
}

public enum PackageManifestError: LocalizedError, Equatable {
    case missing(String)
    case invalid(String)

    public var errorDescription: String? {
        switch self {
        case .missing(let path):
            return "App 缺少平台包清单，禁止连接未知后端。清单路径: \(path)"
        case .invalid(let path):
            return "App 平台包清单无效，禁止连接未知后端。清单路径: \(path)"
        }
    }
}

public struct BackendHealth: Equatable {
    public let ok: Bool
    public let pid: Int?
    public let configPath: String?
    public let runtimeDir: String?
    public let buildID: String?
    public let apiContractVersion: String?
    public let bookkeepingProtocolVersion: String?
    public let capabilities: [String]
    public let buildManifestPresent: Bool
    public let buildManifestValid: Bool
    public let productVersion: String?
    public let packageID: String?
    public let platform: String?
    public let architecture: String?
    public let packageType: String?
    public let packageManifestPresent: Bool
    public let packageManifestValid: Bool

    public init(payload: [String: Any]) {
        ok = payload["ok"] as? Bool == true
        pid = payload["pid"] as? Int
        configPath = payload["config_path"] as? String
        runtimeDir = payload["runtime_dir"] as? String
        buildID = payload["build_id"] as? String
        apiContractVersion = payload["api_contract_version"] as? String
        bookkeepingProtocolVersion = payload["bookkeeping_protocol_version"] as? String
        capabilities = payload["capabilities"] as? [String] ?? []
        buildManifestPresent = payload["build_manifest_present"] as? Bool == true
        buildManifestValid = payload["build_manifest_valid"] as? Bool == true
        productVersion = payload["product_version"] as? String
        packageID = payload["package_id"] as? String
        platform = payload["platform"] as? String
        architecture = payload["architecture"] as? String
        packageType = payload["package_type"] as? String
        packageManifestPresent = payload["package_manifest_present"] as? Bool == true
        packageManifestValid = payload["package_manifest_valid"] as? Bool == true
    }
}

public struct BackendCompatibilityReport: Equatable {
    public static let requiredAPIContractVersion = "2026-08-02-release-update-v1"
    public static let requiredBookkeepingProtocolVersion = "w9-ledger-review-v1"
    public static let requiredCapabilities = [
        "bookkeeping.review",
        "bookkeeping.executability.v2",
        "bookkeeping.import-batch.v1",
        "bookkeeping.import-finalize.v1",
        "bookkeeping.jierui.facts.v2",
        "bookkeeping.jierui.runner.dry-run.v2",
        "bookkeeping.state-cas.v1",
        "bookkeeping.w9-ledger-review.v1",
        "bookkeeping.mapping-resolution.v1",
        "bookkeeping.targeted-recompute.v1",
        "bookkeeping.migration-cas.v2",
        "costs.internal-scroll",
        "documents",
        "documents.validate-outbound-dir",
        "settings.center.v1",
        "settings.preferences.v1",
        "diagnostics.support-package.v1",
        "invoices.batch-print.v1",
        "invoices.classification.v1",
        "invoices.file-preview.v1",
        "invoices.rename-safe.v1",
        "invoices.selection-summary.v1",
        "macos.strict-build-handshake",
        "monitor.ready-handshake.v1",
        "release.package-identity.v1",
        "server.shutdown-choice.v1",
        "settings.startup-surface.v1",
        "skins.zip-portable",
        "updates.metadata-check.v1"
    ]

    public let isCompatible: Bool
    public let issues: [String]

    public static func evaluate(
        health: BackendHealth,
        manifest: InvoiceHubBuildManifest,
        packageManifest: InvoiceHubPackageManifest? = nil,
        paths: BackendPaths
    ) -> BackendCompatibilityReport {
        var issues: [String] = []
        if !health.ok {
            issues.append("health.ok 不是 true")
        }
        if !health.buildManifestPresent {
            issues.append("后端未确认有效构建清单（build_manifest_present 不是 true）")
        }
        if health.buildID != manifest.buildID {
            issues.append("build_id 不匹配（预期 \(manifest.buildID)，实际 \(health.buildID ?? "缺失")）")
        }
        if let packageManifest {
            if !health.buildManifestValid {
                issues.append("后端构建清单未通过发行校验（build_manifest_valid 不是 true）")
            }
            if !health.packageManifestPresent || !health.packageManifestValid {
                issues.append("后端未确认有效平台包清单")
            }
            if packageManifest.coreBuildID != manifest.buildID {
                issues.append("平台包清单 core_build_id 与构建清单不匹配")
            }
            if packageManifest.sourceCommit != manifest.sourceCommit {
                issues.append("平台包清单 source_commit 与构建清单不匹配")
            }
            if health.productVersion != packageManifest.productVersion {
                issues.append("产品版本不匹配（预期 \(packageManifest.productVersion)，实际 \(health.productVersion ?? "缺失")）")
            }
            if health.packageID != packageManifest.packageID {
                issues.append("package_id 不匹配（预期 \(packageManifest.packageID)，实际 \(health.packageID ?? "缺失")）")
            }
            if health.platform != packageManifest.platform
                || health.architecture != packageManifest.architecture
                || health.packageType != packageManifest.packageType {
                issues.append("平台、架构或包类型与平台包清单不匹配")
            }
        }
        if manifest.apiContractVersion != requiredAPIContractVersion {
            issues.append("构建清单 API 契约不受支持（要求 \(requiredAPIContractVersion)，实际 \(manifest.apiContractVersion)）")
        }
        if health.apiContractVersion != requiredAPIContractVersion {
            issues.append("后端 API 契约不受支持（要求 \(requiredAPIContractVersion)，实际 \(health.apiContractVersion ?? "缺失")）")
        }
        if health.apiContractVersion != manifest.apiContractVersion {
            issues.append("API 契约不匹配（预期 \(manifest.apiContractVersion)，实际 \(health.apiContractVersion ?? "缺失")）")
        }
        if manifest.bookkeepingProtocolVersion != requiredBookkeepingProtocolVersion {
            issues.append("构建清单做账协议不受支持（要求 \(requiredBookkeepingProtocolVersion)，实际 \(manifest.bookkeepingProtocolVersion)）")
        }
        if health.bookkeepingProtocolVersion != requiredBookkeepingProtocolVersion {
            issues.append("后端做账协议不受支持（要求 \(requiredBookkeepingProtocolVersion)，实际 \(health.bookkeepingProtocolVersion ?? "缺失")）")
        }
        if health.bookkeepingProtocolVersion != manifest.bookkeepingProtocolVersion {
            issues.append("做账协议不匹配（构建清单 \(manifest.bookkeepingProtocolVersion)，后端 \(health.bookkeepingProtocolVersion ?? "缺失")）")
        }
        let required = Set(requiredCapabilities)
        let manifestCapabilities = Set(manifest.capabilities)
        let healthCapabilities = Set(health.capabilities)
        let manifestMissing = required.subtracting(manifestCapabilities).sorted()
        if !manifestMissing.isEmpty {
            issues.append("构建清单缺少能力: \(manifestMissing.joined(separator: ", "))")
        }
        let healthMissing = required.subtracting(healthCapabilities).sorted()
        if !healthMissing.isEmpty {
            issues.append("后端缺少能力: \(healthMissing.joined(separator: ", "))")
        }
        if manifestCapabilities != required {
            issues.append("构建清单能力集合与客户端要求不匹配")
        }
        if healthCapabilities != required {
            issues.append("后端能力集合与客户端要求不匹配")
        }
        if manifestCapabilities != healthCapabilities {
            issues.append("构建清单与后端能力集合不匹配")
        }
        if canonicalPath(health.configPath) != canonicalPath(paths.configPath.path) {
            issues.append("配置路径不匹配（预期 \(paths.configPath.path)，实际 \(health.configPath ?? "缺失")）")
        }
        if canonicalPath(health.runtimeDir) != canonicalPath(paths.runtimeDir.path) {
            issues.append("运行目录不匹配（预期 \(paths.runtimeDir.path)，实际 \(health.runtimeDir ?? "缺失")）")
        }
        if health.pid.map({ $0 > 0 }) != true {
            issues.append("后端 PID 缺失或无效")
        }
        return BackendCompatibilityReport(isCompatible: issues.isEmpty, issues: issues)
    }

    private static func canonicalPath(_ raw: String?) -> String {
        guard let raw, !raw.isEmpty else { return "" }
        return URL(fileURLWithPath: raw).standardizedFileURL.resolvingSymlinksInPath().path
    }
}
