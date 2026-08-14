import Foundation

public enum StartupSurface: String, Equatable {
    case browser
    case desktop

    public static func normalized(_ value: Any?) -> StartupSurface {
        guard let raw = value as? String else { return .desktop }
        return StartupSurface(rawValue: raw) ?? .desktop
    }
}

public extension Notification.Name {
    static let invoiceHubStartupSurfaceChanged = Notification.Name("InvoiceHubStartupSurfaceChanged")
    static let invoiceHubShowDesktopWindow = Notification.Name("InvoiceHubShowDesktopWindow")
}
