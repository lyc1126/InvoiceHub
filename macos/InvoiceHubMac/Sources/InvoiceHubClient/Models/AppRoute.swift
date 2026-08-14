import Foundation

public enum AppRoute: String, CaseIterable, Identifiable {
    case home
    case costs
    case documents
    case bookkeeping
    case consistency
    case ocr
    case settings
    case skins
    case backend

    public var id: String { rawValue }

    public static let userNavigationRoutes: [AppRoute] = [
        .home, .costs, .documents, .bookkeeping, .ocr, .consistency, .settings
    ]

    public var title: String {
        switch self {
        case .home:
            return "首页"
        case .costs:
            return "成本分析"
        case .documents:
            return "单据"
        case .bookkeeping:
            return "做账"
        case .consistency:
            return "一致性"
        case .ocr:
            return "OCR"
        case .settings:
            return "设置"
        case .skins:
            return "皮肤"
        case .backend:
            return "诊断"
        }
    }

    public var systemImage: String {
        switch self {
        case .home:
            return "doc.text.magnifyingglass"
        case .costs:
            return "tablecells"
        case .documents:
            return "doc.on.doc"
        case .bookkeeping:
            return "checkmark.seal"
        case .consistency:
            return "checklist.checked"
        case .ocr:
            return "text.viewfinder"
        case .settings:
            return "gearshape"
        case .skins:
            return "paintpalette"
        case .backend:
            return "stethoscope"
        }
    }

    public var webPath: String {
        switch self {
        case .home:
            return "/"
        case .costs:
            return "/costs"
        case .documents:
            return "/documents"
        case .bookkeeping:
            return "/bookkeeping"
        case .consistency:
            return "/consistency"
        case .ocr:
            return "/ocr"
        case .settings:
            return "/settings"
        case .skins:
            return "/skins"
        case .backend:
            return "/backend"
        }
    }
}
