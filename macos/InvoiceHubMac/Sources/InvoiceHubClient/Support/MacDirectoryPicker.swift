import AppKit
import Foundation

public enum MacDirectoryPicker {
    @MainActor
    public static func pickDirectory(title: String) -> URL? {
        let panel = NSOpenPanel()
        panel.title = title
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        panel.canCreateDirectories = true
        panel.prompt = "选择"
        return panel.runModal() == .OK ? panel.url : nil
    }
}
