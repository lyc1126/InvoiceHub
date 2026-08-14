import AppKit
import SwiftUI
import UniformTypeIdentifiers
@preconcurrency import WebKit

struct WebFilePickerPolicy: Equatable {
    let canChooseFiles: Bool
    let canChooseDirectories: Bool
    let allowsMultipleSelection: Bool
    let allowedContentTypes: [UTType]

    static func resolve(
        pagePath: String?,
        allowsDirectories: Bool,
        allowsMultipleSelection: Bool
    ) -> WebFilePickerPolicy {
        WebFilePickerPolicy(
            canChooseFiles: !allowsDirectories,
            canChooseDirectories: allowsDirectories,
            allowsMultipleSelection: allowsMultipleSelection,
            allowedContentTypes: pagePath == AppRoute.skins.webPath ? [.zip] : []
        )
    }
}

struct WebOriginPolicy {
    static func allowsMainFrameURL(_ candidate: URL?, expectedBaseURL: URL, isMainFrame: Bool) -> Bool {
        guard isMainFrame, let candidate else { return false }
        guard
            expectedBaseURL.scheme?.lowercased() == "http",
            expectedBaseURL.host?.lowercased() == "127.0.0.1",
            candidate.scheme?.lowercased() == "http",
            candidate.host?.lowercased() == "127.0.0.1",
            candidate.user == nil,
            candidate.password == nil
        else {
            return false
        }
        return effectivePort(candidate) == effectivePort(expectedBaseURL)
    }

    static func allowsScriptMessage(
        scheme: String,
        host: String,
        port: Int,
        expectedBaseURL: URL,
        isMainFrame: Bool
    ) -> Bool {
        guard isMainFrame else { return false }
        guard
            expectedBaseURL.scheme?.lowercased() == "http",
            expectedBaseURL.host?.lowercased() == "127.0.0.1",
            scheme.lowercased() == "http",
            host.lowercased() == "127.0.0.1"
        else {
            return false
        }
        return port == effectivePort(expectedBaseURL)
    }

    private static func effectivePort(_ url: URL) -> Int {
        url.port ?? (url.scheme?.lowercased() == "http" ? 80 : -1)
    }
}

struct WebPopupPolicy {
    static func allowsCreation(
        sourceURL: URL?,
        requestedURL: URL?,
        sourceScheme: String,
        sourceHost: String,
        sourcePort: Int,
        expectedBaseURL: URL,
        sourceIsMainFrame: Bool
    ) -> Bool {
        guard sourceIsMainFrame else { return false }
        guard WebOriginPolicy.allowsMainFrameURL(
            sourceURL,
            expectedBaseURL: expectedBaseURL,
            isMainFrame: true
        ) else {
            return false
        }
        guard WebOriginPolicy.allowsScriptMessage(
            scheme: sourceScheme,
            host: sourceHost,
            port: sourcePort,
            expectedBaseURL: expectedBaseURL,
            isMainFrame: true
        ) else {
            return false
        }
        return isExactAboutBlank(requestedURL)
    }

    static func isExactAboutBlank(_ candidate: URL?) -> Bool {
        candidate?.absoluteString.lowercased() == "about:blank"
    }

    static func allowsInitialPopupBlankNavigation(
        _ candidate: URL?,
        sourceIsMainFrame: Bool,
        targetIsMainFrame: Bool?
    ) -> Bool {
        guard sourceIsMainFrame, isExactAboutBlank(candidate) else { return false }
        // WebKit reports a nil target while handing the one new-window navigation to the
        // delegate-created WebView. It is never accepted for a later print-route navigation.
        return targetIsMainFrame != false
    }

    static func printPathForPopupNavigation(
        _ candidate: URL?,
        expectedBaseURL: URL,
        sourceIsMainFrame: Bool,
        targetIsMainFrame: Bool?
    ) -> String? {
        guard targetIsMainFrame == true else { return nil }
        return printPath(
            for: candidate,
            expectedBaseURL: expectedBaseURL,
            isMainFrame: sourceIsMainFrame
        )
    }

    static func printPath(
        for candidate: URL?,
        expectedBaseURL: URL,
        isMainFrame: Bool
    ) -> String? {
        guard WebOriginPolicy.allowsMainFrameURL(
            candidate,
            expectedBaseURL: expectedBaseURL,
            isMainFrame: isMainFrame
        ), let candidate, candidate.query == nil, candidate.fragment == nil else {
            return nil
        }
        // URL.path normalizes a terminal slash; compare the unnormalized component first.
        guard URLComponents(url: candidate, resolvingAgainstBaseURL: false)?.percentEncodedPath == candidate.path else {
            return nil
        }
        let components = candidate.path.split(separator: "/", omittingEmptySubsequences: false)
        guard
            components.count == 4,
            components[0].isEmpty,
            components[1] == "invoices",
            components[2] == "print"
        else {
            return nil
        }
        let jobID = components[3]
        guard !jobID.isEmpty, jobID.unicodeScalars.allSatisfy(isSafeJobIDScalar) else {
            return nil
        }
        return candidate.path
    }

    private static func isSafeJobIDScalar(_ scalar: Unicode.Scalar) -> Bool {
        switch scalar.value {
        case 45, 48...57, 65...90, 95, 97...122:
            return true
        default:
            return false
        }
    }
}

struct WebPrintPolicy {
    static func allowsPrintBridgeMessage(
        action: String?,
        pageURL: URL?,
        registeredPrintPath: String?,
        scheme: String,
        host: String,
        port: Int,
        expectedBaseURL: URL,
        isMainFrame: Bool
    ) -> Bool {
        guard action == "print", let registeredPrintPath else { return false }
        guard WebOriginPolicy.allowsScriptMessage(
            scheme: scheme,
            host: host,
            port: port,
            expectedBaseURL: expectedBaseURL,
            isMainFrame: isMainFrame
        ) else {
            return false
        }
        return WebPopupPolicy.printPath(
            for: pageURL,
            expectedBaseURL: expectedBaseURL,
            isMainFrame: isMainFrame
        ) == registeredPrintPath
    }
}

/// Closed print popups deliberately remain strongly retained for the rest of this process.
/// WebKit does not expose a completion point after an NSWindow close at which its WebView graph
/// is documented to be safe to release, so a timer cannot establish that safety boundary.
final class PrintPopupQuarantine<Popup: AnyObject> {
    private var retiredPopups: [Popup] = []

    func retain(_ popup: Popup) {
        retiredPopups.append(popup)
    }

    var retainedCount: Int {
        retiredPopups.count
    }

    func contains(_ popup: Popup) -> Bool {
        retiredPopups.contains { $0 === popup }
    }
}

/// Tracks only live popup WebViews. Retirement removes a popup from the message-accepting
/// registry before handing its ownership to the process-lifetime quarantine.
final class PrintPopupRegistry<Popup: AnyObject> {
    private var activePopups: [ObjectIdentifier: Popup] = [:]
    private let retirePopup: (Popup) -> Void

    init(retirePopup: @escaping (Popup) -> Void) {
        self.retirePopup = retirePopup
    }

    func register(_ popup: Popup, for owner: AnyObject) {
        activePopups[ObjectIdentifier(owner)] = popup
    }

    func activePopup(for owner: AnyObject) -> Popup? {
        activePopups[ObjectIdentifier(owner)]
    }

    var activeValues: [Popup] {
        Array(activePopups.values)
    }

    var activeCount: Int {
        activePopups.count
    }

    @discardableResult
    func retireActivePopup(
        matching predicate: (Popup) -> Bool,
        beforeRetire: (Popup) -> Void
    ) -> Bool {
        guard let activePopup = activePopups.first(where: { predicate($0.value) }) else {
            return false
        }
        beforeRetire(activePopup.value)
        activePopups.removeValue(forKey: activePopup.key)
        retirePopup(activePopup.value)
        return true
    }
}

private let processLifetimePrintPopupQuarantine = PrintPopupQuarantine<AnyObject>()

struct PrintPopupLifecycle {
    private(set) var isClosing = false
    private(set) var printOperationActive = false

    mutating func beginPrintOperation() -> Bool {
        guard !isClosing, !printOperationActive else { return false }
        printOperationActive = true
        return true
    }

    mutating func finishPrintOperation() {
        printOperationActive = false
    }

    mutating func beginClosing() {
        isClosing = true
    }
}

enum WebPopupConfigurationPolicy {
    @discardableResult
    static func installRestrictedPrintBridge(
        on configuration: WKWebViewConfiguration,
        messageHandler: WKScriptMessageHandler
    ) -> WKUserContentController {
        // WebKit requires the delegate-supplied configuration for a new page. Replace only
        // its inherited content controller so a print popup never receives the main bridge.
        let contentController = WKUserContentController()
        contentController.add(messageHandler, name: "invoiceHubMacPrint")
        contentController.addUserScript(WKUserScript(
            source: WebView.printBridgeScript(),
            injectionTime: .atDocumentStart,
            forMainFrameOnly: true
        ))
        configuration.userContentController = contentController
        return contentController
    }
}

public struct WebView: NSViewRepresentable {
    public let url: URL
    public let backend: LocalBackendController

    public init(url: URL, backend: LocalBackendController) {
        self.url = url
        self.backend = backend
    }

    public func makeCoordinator() -> Coordinator {
        Coordinator(backend: backend, allowedOrigin: url)
    }

    public func makeNSView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = true
        let contentController = WKUserContentController()
        contentController.add(context.coordinator, name: "invoiceHubMac")
        contentController.addUserScript(WKUserScript(
            source: Self.bridgeScript(
                for: backend.ownership,
                canInstallUpdate: backend.canInstallUpdate
            ),
            injectionTime: .atDocumentStart,
            forMainFrameOnly: true
        ))
        configuration.userContentController = contentController

        let webView = WKWebView(frame: .zero, configuration: configuration)
        context.coordinator.webView = webView
        webView.uiDelegate = context.coordinator
        webView.navigationDelegate = context.coordinator
        webView.allowsBackForwardNavigationGestures = true
        webView.load(URLRequest(url: url))
        return webView
    }

    public func updateNSView(_ nsView: WKWebView, context: Context) {
        if nsView.url != url {
            nsView.load(URLRequest(url: url))
        }
    }

    public static func dismantleNSView(_ nsView: WKWebView, coordinator: Coordinator) {
        nsView.configuration.userContentController.removeScriptMessageHandler(forName: "invoiceHubMac")
        nsView.uiDelegate = nil
        nsView.navigationDelegate = nil
        coordinator.closePrintPopups()
        coordinator.webView = nil
    }

    static func bridgeScript(
        for ownership: BackendOwnership,
        canInstallUpdate: Bool? = nil
    ) -> String {
        let canManageBackend = ownership.canStopOrRestart ? "true" : "false"
        let permitsInstallUpdate = canInstallUpdate ?? ownership.canStopOrRestart
        let updateInstallBridge = permitsInstallUpdate ? """
        installUpdate() {
          const id = String(nextId++);
          return new Promise((resolve, reject) => {
            pending.set(id, { resolve, reject });
            window.webkit.messageHandlers.invoiceHubMac.postMessage({ id, action: "installUpdate" });
          });
        },
        """ : ""
        return """
    (() => {
      if (window.invoiceHubMac) return;
      let nextId = 1;
      const pending = new Map();
      window.invoiceHubMac = {
        backendOwnership: "\(ownership.rawValue)",
        canManageBackend: \(canManageBackend),
        canInstallUpdate: \(permitsInstallUpdate ? "true" : "false"),
        pickWatchDir() {
          const id = String(nextId++);
          return new Promise((resolve, reject) => {
            pending.set(id, { resolve, reject });
            window.webkit.messageHandlers.invoiceHubMac.postMessage({ id, action: "pickWatchDir" });
          });
        },
        pickOutboundDir() {
          const id = String(nextId++);
          return new Promise((resolve, reject) => {
            pending.set(id, { resolve, reject });
            window.webkit.messageHandlers.invoiceHubMac.postMessage({ id, action: "pickOutboundDir" });
          });
        },
        pickOcrCandidateDir() {
          const id = String(nextId++);
          return new Promise((resolve, reject) => {
            pending.set(id, { resolve, reject });
            window.webkit.messageHandlers.invoiceHubMac.postMessage({ id, action: "pickOcrCandidateDir" });
          });
        },
    \(updateInstallBridge)
        __resolve(id, payload) {
          const entry = pending.get(String(id));
          if (!entry) return;
          pending.delete(String(id));
          entry.resolve(payload);
        },
        __reject(id, message) {
          const entry = pending.get(String(id));
          if (!entry) return;
          pending.delete(String(id));
          entry.reject(new Error(message || "macOS bridge failed"));
        }
      };
    })();
    """
    }

    static func printBridgeScript() -> String {
        """
    (() => {
      // Keep the creator's WindowProxy usable for location.replace(), but never let this
      // same-origin print document reach the main WebView's native bridge through opener.
      try { window.opener = null; } catch (_error) {}
      try {
        Object.defineProperty(window, "opener", {
          value: null,
          writable: false,
          configurable: false
        });
      } catch (_error) {}
      if (window.__invoiceHubMacPrintBridgeInstalled) return;
      Object.defineProperty(window, "__invoiceHubMacPrintBridgeInstalled", { value: true, configurable: false });
      var printInFlight = false;
      const finishPrint = () => {
        if (!printInFlight) return;
        printInFlight = false;
        try { window.dispatchEvent(new Event("afterprint")); } catch (_error) {}
      };
      Object.defineProperty(window, "__invoiceHubMacFinishPrint", { value: finishPrint, configurable: false });
      window.print = () => {
        if (printInFlight) return;
        printInFlight = true;
        try { window.dispatchEvent(new Event("beforeprint")); } catch (_error) {}
        const handler = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.invoiceHubMacPrint;
        if (!handler) {
          finishPrint();
          return;
        }
        try {
          handler.postMessage({ action: "print" });
        } catch (_error) {
          finishPrint();
        }
      };
    })();
    """
    }

    public final class Coordinator: NSObject, WKScriptMessageHandler, WKUIDelegate, WKNavigationDelegate, NSWindowDelegate {
        private final class PrintPopup {
            let window: NSWindow
            let webView: WKWebView
            let messageHandler: PrintMessageHandler
            var initialBlankNavigationPending = true
            var registeredPrintPath: String?
            var lifecycle = PrintPopupLifecycle()

            init(window: NSWindow, webView: WKWebView, messageHandler: PrintMessageHandler) {
                self.window = window
                self.webView = webView
                self.messageHandler = messageHandler
            }
        }

        private final class PrintMessageHandler: NSObject, WKScriptMessageHandler {
            weak var coordinator: Coordinator?
            weak var popupWebView: WKWebView?

            init(coordinator: Coordinator) {
                self.coordinator = coordinator
            }

            func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
                guard let popupWebView else { return }
                coordinator?.handlePrintMessage(message, from: popupWebView)
            }
        }

        weak var webView: WKWebView?
        private let backend: LocalBackendController
        private let allowedOrigin: URL
        private let printPopups: PrintPopupRegistry<PrintPopup>

        init(backend: LocalBackendController, allowedOrigin: URL) {
            self.backend = backend
            self.allowedOrigin = allowedOrigin
            self.printPopups = PrintPopupRegistry { popup in
                processLifetimePrintPopupQuarantine.retain(popup)
            }
        }

        public func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
            guard
                message.name == "invoiceHubMac",
                WebOriginPolicy.allowsScriptMessage(
                    scheme: message.frameInfo.securityOrigin.protocol,
                    host: message.frameInfo.securityOrigin.host,
                    port: message.frameInfo.securityOrigin.port,
                    expectedBaseURL: allowedOrigin,
                    isMainFrame: message.frameInfo.isMainFrame
                ),
                let body = message.body as? [String: Any],
                let action = body["action"] as? String,
                let id = body["id"] as? String
            else {
                return
            }

            switch action {
            case "pickWatchDir":
                Task { @MainActor in
                    do {
                        let payload = try await backend.pickWatchDirectoryDraft()
                        resolve(id: id, payload: payload)
                    } catch {
                        reject(id: id, message: error.localizedDescription)
                    }
                }
            case "pickOutboundDir":
                Task { @MainActor in
                    do {
                        let payload = try await backend.pickOutboundDirectoryDraft()
                        resolve(id: id, payload: payload)
                    } catch {
                        reject(id: id, message: error.localizedDescription)
                    }
                }
            case "pickOcrCandidateDir":
                Task { @MainActor in
                    resolve(id: id, payload: backend.pickOCRCandidateDirectoryDraft())
                }
            case "installUpdate":
                Task { @MainActor in
                    guard backend.canInstallUpdate else {
                        reject(id: id, message: BackendUpdateError.ownedLifecycleRequired.localizedDescription)
                        return
                    }
                    do {
                        resolve(id: id, payload: try backend.installUpdate())
                    } catch {
                        reject(id: id, message: error.localizedDescription)
                    }
                }
            default:
                reject(id: id, message: "Unknown macOS bridge action: \(action)")
            }
        }

        public func webView(
            _ webView: WKWebView,
            decidePolicyFor navigationAction: WKNavigationAction,
            decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
        ) {
            if webView === self.webView {
                if navigationAction.targetFrame == nil,
                   WebPopupPolicy.allowsCreation(
                    sourceURL: webView.url,
                    requestedURL: navigationAction.request.url,
                    sourceScheme: navigationAction.sourceFrame.securityOrigin.protocol,
                    sourceHost: navigationAction.sourceFrame.securityOrigin.host,
                    sourcePort: navigationAction.sourceFrame.securityOrigin.port,
                    expectedBaseURL: allowedOrigin,
                    sourceIsMainFrame: navigationAction.sourceFrame.isMainFrame
                   ) {
                    decisionHandler(.allow)
                    return
                }
                let url = navigationAction.request.url
                let allowed = WebOriginPolicy.allowsMainFrameURL(
                    url,
                    expectedBaseURL: allowedOrigin,
                    isMainFrame: navigationAction.targetFrame?.isMainFrame == true
                )
                guard !allowed else {
                    decisionHandler(.allow)
                    return
                }
                decisionHandler(.cancel)
                if navigationAction.navigationType == .linkActivated,
                   let url,
                   ["http", "https"].contains(url.scheme?.lowercased() ?? "") {
                    NSWorkspace.shared.open(url)
                }
                return
            }

            guard let popup = printPopups.activePopup(for: webView) else {
                decisionHandler(.cancel)
                return
            }
            let url = navigationAction.request.url
            let sourceIsMainFrame = navigationAction.sourceFrame.isMainFrame
            let targetIsMainFrame = navigationAction.targetFrame?.isMainFrame
            if popup.initialBlankNavigationPending,
               WebPopupPolicy.allowsInitialPopupBlankNavigation(
                url,
                sourceIsMainFrame: sourceIsMainFrame,
                targetIsMainFrame: targetIsMainFrame
               ) {
                popup.initialBlankNavigationPending = false
                decisionHandler(.allow)
                return
            }
            guard let printPath = WebPopupPolicy.printPathForPopupNavigation(
                url,
                expectedBaseURL: allowedOrigin,
                sourceIsMainFrame: sourceIsMainFrame,
                targetIsMainFrame: targetIsMainFrame
            ) else {
                decisionHandler(.cancel)
                return
            }
            guard popup.registeredPrintPath == nil || popup.registeredPrintPath == printPath else {
                decisionHandler(.cancel)
                return
            }
            popup.initialBlankNavigationPending = false
            popup.registeredPrintPath = printPath
            decisionHandler(.allow)
        }

        public func webView(
            _ webView: WKWebView,
            createWebViewWith configuration: WKWebViewConfiguration,
            for navigationAction: WKNavigationAction,
            windowFeatures: WKWindowFeatures
        ) -> WKWebView? {
            guard webView === self.webView else { return nil }
            guard WebPopupPolicy.allowsCreation(
                sourceURL: webView.url,
                requestedURL: navigationAction.request.url,
                sourceScheme: navigationAction.sourceFrame.securityOrigin.protocol,
                sourceHost: navigationAction.sourceFrame.securityOrigin.host,
                sourcePort: navigationAction.sourceFrame.securityOrigin.port,
                expectedBaseURL: allowedOrigin,
                sourceIsMainFrame: navigationAction.sourceFrame.isMainFrame
            ) else {
                return nil
            }

            let messageHandler = PrintMessageHandler(coordinator: self)
            WebPopupConfigurationPolicy.installRestrictedPrintBridge(
                on: configuration,
                messageHandler: messageHandler
            )

            let popupWebView = WKWebView(frame: .zero, configuration: configuration)
            popupWebView.uiDelegate = self
            popupWebView.navigationDelegate = self
            popupWebView.allowsBackForwardNavigationGestures = false
            messageHandler.popupWebView = popupWebView

            let window = NSWindow(
                contentRect: NSRect(x: 0, y: 0, width: 980, height: 760),
                styleMask: [.titled, .closable, .miniaturizable, .resizable],
                backing: .buffered,
                defer: false
            )
            window.isReleasedWhenClosed = false
            window.title = "发票打印"
            window.contentView = popupWebView
            window.delegate = self
            let popup = PrintPopup(
                window: window,
                webView: popupWebView,
                messageHandler: messageHandler
            )
            printPopups.register(popup, for: popupWebView)
            window.center()
            window.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return popupWebView
        }

        public func webViewDidClose(_ webView: WKWebView) {
            guard let popup = printPopups.activePopup(for: webView), !popup.lifecycle.isClosing else { return }
            popup.window.close()
        }

        public func webView(
            _ webView: WKWebView,
            runOpenPanelWith parameters: WKOpenPanelParameters,
            initiatedByFrame frame: WKFrameInfo,
            completionHandler: @escaping ([URL]?) -> Void
        ) {
            guard webView === self.webView, WebOriginPolicy.allowsScriptMessage(
                scheme: frame.securityOrigin.protocol,
                host: frame.securityOrigin.host,
                port: frame.securityOrigin.port,
                expectedBaseURL: allowedOrigin,
                isMainFrame: frame.isMainFrame
            ) else {
                completionHandler(nil)
                return
            }
            let policy = WebFilePickerPolicy.resolve(
                pagePath: webView.url?.path,
                allowsDirectories: parameters.allowsDirectories,
                allowsMultipleSelection: parameters.allowsMultipleSelection
            )
            let panel = NSOpenPanel()
            panel.canChooseFiles = policy.canChooseFiles
            panel.canChooseDirectories = policy.canChooseDirectories
            panel.allowsMultipleSelection = policy.allowsMultipleSelection
            panel.resolvesAliases = true
            panel.canCreateDirectories = false
            panel.prompt = "选择"

            if !policy.allowedContentTypes.isEmpty {
                panel.allowedContentTypes = policy.allowedContentTypes
                panel.title = "选择皮肤包"
                panel.message = "请选择 ZIP 格式的皮肤包"
            }

            let finish: (NSApplication.ModalResponse) -> Void = { response in
                completionHandler(response == .OK ? panel.urls : nil)
            }
            if let window = webView.window {
                panel.beginSheetModal(for: window, completionHandler: finish)
            } else {
                finish(panel.runModal())
            }
        }

        public func windowWillClose(_ notification: Notification) {
            guard let window = notification.object as? NSWindow else { return }
            // Refuse late messages, then remove the popup from the active registry. Its window,
            // WebView and handler move to a process-lifetime quarantine rather than being
            // released from AppKit's close callback or a guessed future run-loop turn.
            _ = printPopups.retireActivePopup(
                matching: { $0.window === window },
                beforeRetire: { popup in
                    popup.lifecycle.beginClosing()
                    popup.messageHandler.coordinator = nil
                }
            )
        }

        fileprivate func closePrintPopups() {
            let popups = printPopups.activeValues
            for popup in popups {
                if !popup.lifecycle.isClosing {
                    popup.window.close()
                }
            }
        }

        private func handlePrintMessage(_ message: WKScriptMessage, from popupWebView: WKWebView) {
            guard message.name == "invoiceHubMacPrint",
                  let popup = printPopups.activePopup(for: popupWebView)
            else {
                return
            }
            guard
                  let body = message.body as? [String: Any],
                  let action = body["action"] as? String,
                  WebPrintPolicy.allowsPrintBridgeMessage(
                    action: action,
                    pageURL: popupWebView.url,
                    registeredPrintPath: popup.registeredPrintPath,
                    scheme: message.frameInfo.securityOrigin.protocol,
                    host: message.frameInfo.securityOrigin.host,
                    port: message.frameInfo.securityOrigin.port,
                    expectedBaseURL: allowedOrigin,
                    isMainFrame: message.frameInfo.isMainFrame
                  )
            else {
                if !popup.lifecycle.isClosing, !popup.lifecycle.printOperationActive {
                    finishPrintBridge(on: popupWebView)
                }
                return
            }
            guard popup.lifecycle.beginPrintOperation() else { return }
            DispatchQueue.main.async { [weak self, weak popupWebView, weak popup] in
                guard let self, let popup else { return }
                guard let popupWebView,
                      let currentPopup = self.printPopups.activePopup(for: popupWebView),
                      currentPopup === popup,
                      !currentPopup.lifecycle.isClosing,
                      WebPrintPolicy.allowsPrintBridgeMessage(
                        action: "print",
                        pageURL: popupWebView.url,
                        registeredPrintPath: currentPopup.registeredPrintPath,
                        scheme: "http",
                        host: "127.0.0.1",
                        port: self.allowedOrigin.port ?? 80,
                        expectedBaseURL: self.allowedOrigin,
                        isMainFrame: true
                      )
                else {
                    popup.lifecycle.finishPrintOperation()
                    if !popup.lifecycle.isClosing, let popupWebView {
                        self.finishPrintBridge(on: popupWebView)
                    }
                    return
                }
                let operation = popupWebView.printOperation(with: NSPrintInfo.shared)
                operation.showsPrintPanel = true
                operation.showsProgressPanel = true
                _ = operation.run()
                currentPopup.lifecycle.finishPrintOperation()
                if !currentPopup.lifecycle.isClosing {
                    finishPrintBridge(on: popupWebView)
                }
            }
        }

        private func finishPrintBridge(on webView: WKWebView) {
            webView.evaluateJavaScript(
                "window.__invoiceHubMacFinishPrint && window.__invoiceHubMacFinishPrint();"
            )
        }

        private func resolve(id: String, payload: [String: Any]) {
            guard let payloadLiteral = jsonLiteral(payload) else {
                reject(id: id, message: "Cannot encode macOS bridge payload.")
                return
            }
            evaluate("window.invoiceHubMac && window.invoiceHubMac.__resolve(\(stringLiteral(id)), \(payloadLiteral));")
        }

        private func reject(id: String, message: String) {
            evaluate("window.invoiceHubMac && window.invoiceHubMac.__reject(\(stringLiteral(id)), \(stringLiteral(message)));")
        }

        private func evaluate(_ script: String) {
            DispatchQueue.main.async { [weak self] in
                self?.webView?.evaluateJavaScript(script)
            }
        }

        private func jsonLiteral(_ payload: [String: Any]) -> String? {
            guard JSONSerialization.isValidJSONObject(payload),
                  let data = try? JSONSerialization.data(withJSONObject: payload, options: [])
            else {
                return nil
            }
            return String(data: data, encoding: .utf8)
        }

        private func stringLiteral(_ value: String) -> String {
            let data = try? JSONEncoder().encode(value)
            return data.flatMap { String(data: $0, encoding: .utf8) } ?? "\"\""
        }
    }
}
