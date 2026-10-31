// Forthmark menu bar app: a native shell around the local panel.
//
// - Menu bar item shows a summary ("⏳9 📣1"); left click opens the panel (the same
//   HUD page the browser shows) in a popover; right click shows the menu.
// - Starts the local service (forthmark.py serve) when it isn't running.
// - Posts the daily nudges as its own notifications; clicking one opens the panel.
// - "Open at login" uses SMAppService, switched on by the user from the menu.
//
// Built by tools/build_app.sh, which stamps the kit path and python into Info.plist.

import Cocoa
import ServiceManagement
import UserNotifications
import WebKit

final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate, WKUIDelegate, UNUserNotificationCenterDelegate,
    WKScriptMessageHandler, NSWindowDelegate {
    private var statusItem: NSStatusItem!
    private let popover = NSPopover()
    private var webView: WKWebView!
    private var serverProcess: Process?
    private var timers: [Timer] = []
    private var windows: [NSWindow] = []

    private let home = forthmarkHome
    private let kit = Bundle.main.object(forInfoDictionaryKey: "ForthmarkKit") as? String ?? ""
    private let python = Bundle.main.object(forInfoDictionaryKey: "ForthmarkPython") as? String ?? "/usr/bin/python3"

    // MARK: lifecycle

    func applicationDidFinishLaunching(_ notification: Notification) {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let button = statusItem.button {
            button.image = forthmarkTemplateImage(height: 17)
            button.imagePosition = .imageLeading
            button.target = self
            button.action = #selector(statusItemClicked)
            button.sendAction(on: [.leftMouseUp, .rightMouseUp])
        }

        webView = makeWebView(NSRect(x: 0, y: 0, width: 460, height: 760))
        // Transparent page over the popover's own material: frosted vibrancy on macOS 15,
        // Liquid Glass on macOS 26 (built against its SDK, NSPopover adopts it automatically).
        webView.setValue(false, forKey: "drawsBackground")
        webView.underPageBackgroundColor = .clear
        let controller = NSViewController()
        controller.view = webView
        popover.contentViewController = controller
        popover.contentSize = NSSize(width: 460, height: 760)
        popover.behavior = .transient

        let center = UNUserNotificationCenter.current()
        center.delegate = self
        center.requestAuthorization(options: [.alert, .sound]) { _, _ in }

        ensureServer { [weak self] in
            self?.refreshBadge()
            self?.loadPanel()
        }
        timers.append(Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { [weak self] _ in self?.refreshBadge() })
        timers.append(Timer.scheduledTimer(withTimeInterval: 30 * 60, repeats: true) { [weak self] _ in self?.checkNotifications() })
        DispatchQueue.main.asyncAfter(deadline: .now() + 60) { [weak self] in self?.checkNotifications() }
    }

    func applicationWillTerminate(_ notification: Notification) {
        serverProcess?.terminate()  // only the service this app started; one started elsewhere keeps running
    }

    // MARK: local service

    private struct Server { let port: Int; let token: String }

    private func serverInfo() -> Server? {
        let path = (home as NSString).appendingPathComponent("server.json")
        guard let data = FileManager.default.contents(atPath: path),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let port = obj["port"] as? Int, let token = obj["token"] as? String else { return nil }
        return Server(port: port, token: token)
    }

    private func isAlive(_ done: @escaping (Bool) -> Void) {
        guard let s = serverInfo(), let url = URL(string: "http://127.0.0.1:\(s.port)/api/ping") else { return done(false) }
        var req = URLRequest(url: url)
        req.timeoutInterval = 1
        URLSession.shared.dataTask(with: req) { data, _, _ in
            let obj = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
            let ok = (obj?["home"] as? String) == self.home  // another data dir's service doesn't count
            DispatchQueue.main.async { done(ok) }
        }.resume()
    }

    private func ensureServer(_ ready: @escaping () -> Void) {
        isAlive { [weak self] alive in
            guard let self else { return }
            if alive { return ready() }
            let p = Process()
            p.executableURL = URL(fileURLWithPath: self.python)
            p.arguments = [(self.kit as NSString).appendingPathComponent("tools/forthmark.py"), "serve"]
            // Don't hand a Claude Code session's variables (child-session marker, messaging token) to the service.
            let sessionVars: Set<String> = ["CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_ENTRYPOINT",
                "CLAUDE_CODE_EXECPATH", "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN",
                "CLAUDE_CODE_SESSION_ATTENDED", "CLAUDE_CODE_SESSION_ID", "CLAUDE_EFFORT", "CLAUDE_JOB_DIR", "CLAUDE_PID"]
            p.environment = ProcessInfo.processInfo.environment.filter { !sessionVars.contains($0.key) }
            let log = (self.home as NSString).appendingPathComponent("server.log")
            if !FileManager.default.fileExists(atPath: log) { FileManager.default.createFile(atPath: log, contents: nil) }
            if let fh = FileHandle(forWritingAtPath: log) { fh.seekToEndOfFile(); p.standardOutput = fh; p.standardError = fh }
            do { try p.run(); self.serverProcess = p } catch { self.setTitle("!", tip: L("无法启动本地服务：", "Couldn't start the local service: ") + error.localizedDescription); return }
            self.waitForServer(tries: 30, ready)
        }
    }

    private func waitForServer(tries: Int, _ ready: @escaping () -> Void) {
        isAlive { [weak self] alive in
            if alive { return ready() }
            guard tries > 0 else { self?.setTitle("!", tip: L("本地服务没有启动，见 ~/.forthmark/server.log", "The local service didn't start; see ~/.forthmark/server.log")); return }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { self?.waitForServer(tries: tries - 1, ready) }
        }
    }

    private func api(_ path: String, _ done: @escaping (Data?) -> Void) {
        guard let s = serverInfo(), let url = URL(string: "http://127.0.0.1:\(s.port)\(path)") else { return done(nil) }
        var req = URLRequest(url: url)
        req.setValue(s.token, forHTTPHeaderField: "X-Forthmark-Token")
        req.timeoutInterval = 10
        URLSession.shared.dataTask(with: req) { data, resp, _ in
            let ok = (resp as? HTTPURLResponse)?.statusCode == 200
            DispatchQueue.main.async { done(ok ? data : nil) }
        }.resume()
    }

    // MARK: menu bar item

    private func setTitle(_ text: String, tip: String) {
        guard let button = statusItem.button else { return }
        // Plain monospaced digits next to the template icon: one glyph group, matches other menu bar items.
        button.attributedTitle = NSAttributedString(string: text.isEmpty ? "" : " " + text,
            attributes: [.font: NSFont.monospacedDigitSystemFont(ofSize: NSFont.systemFontSize, weight: .medium)])
        button.toolTip = tip
    }

    private func refreshBadge() {
        api("/api/badge") { [weak self] data in
            guard let self else { return }
            guard let data, let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                // Service gone: bring it back. Service up but API failing (e.g. an older version without a
                // token): say so and try again on the next tick instead of looping.
                return self.isAlive { alive in
                    if alive { self.setTitle("!", tip: L("本地服务需要重启：forthmark.py stop，然后点菜单里的「刷新」", "The local service needs a restart: run forthmark.py stop, then Refresh from the menu")) }
                    else { self.ensureServer { self.refreshBadge() } }
                }
            }
            self.setTitle(obj["text"] as? String ?? "", tip: obj["tooltip"] as? String ?? "")
        }
    }

    @objc private func statusItemClicked() {
        // Option-click: straight to the panel window (like Option-click on system menu bar items).
        if NSApp.currentEvent?.type == .leftMouseUp, NSApp.currentEvent?.modifierFlags.contains(.option) == true {
            return openPanelWindow()
        }
        if NSApp.currentEvent?.type == .rightMouseUp {
            statusItem.menu = buildMenu()
            statusItem.button?.performClick(nil)
        } else {
            togglePopover()
        }
    }

    func menuDidClose(_ menu: NSMenu) { statusItem.menu = nil }  // so the next left click opens the panel again

    private func buildMenu() -> NSMenu {
        let menu = NSMenu()
        menu.delegate = self
        menu.addItem(withTitle: L("打开面板窗口", "Open Panel Window"), action: #selector(openPanelWindowFromMenu), keyEquivalent: "o").target = self
        menu.addItem(withTitle: L("在浏览器打开", "Open in Browser"), action: #selector(openInBrowser), keyEquivalent: "").target = self
        menu.addItem(withTitle: L("刷新", "Refresh"), action: #selector(refreshAll), keyEquivalent: "r").target = self
        menu.addItem(.separator())
        let login = menu.addItem(withTitle: L("开机自启", "Launch at Login"), action: #selector(toggleLoginItem), keyEquivalent: "")
        login.target = self
        login.state = SMAppService.mainApp.status == .enabled ? .on : .off
        menu.addItem(withTitle: L("发送测试通知", "Send Test Notification"), action: #selector(testNotification), keyEquivalent: "").target = self
        menu.addItem(.separator())
        menu.addItem(withTitle: L("退出 Forthmark", "Quit Forthmark"), action: #selector(quit), keyEquivalent: "q").target = self
        return menu
    }

    private func panelURL() -> URL? {
        serverInfo().flatMap { URL(string: "http://127.0.0.1:\($0.port)/") }
    }

    private func loadPanel() {
        guard let base = panelURL(), var parts = URLComponents(url: base, resolvingAgainstBaseURL: false) else { return }
        parts.fragment = "shell=popover"  // tells the page to render translucent
        if let url = parts.url { webView.load(URLRequest(url: url)) }
    }

    // MARK: web views and windows

    /// Every web view gets the same native bridges: dialogs, external links, and window.webkit.messageHandlers.forthmark.
    private func makeWebView(_ frame: NSRect) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.userContentController.add(self, name: "forthmark")
        let view = WKWebView(frame: frame, configuration: config)
        view.uiDelegate = self
        return view
    }

    /// The panel asks for a window (e.g. a document from the narrow popover).
    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        if (message.body as? [String: Any])?["action"] as? String == "openPanel" {
            return openPanelWindow(newProject: (message.body as? [String: Any])?["newProject"] as? Bool ?? false)
        }
        if let body = message.body as? [String: Any], body["action"] as? String == "resize",
           let h = body["height"] as? Double, message.webView === webView {
            // Fit the popover to its content, up to 85% of the screen; beyond that the page scrolls.
            let maxH = (NSScreen.main?.visibleFrame.height ?? 900) * 0.85
            let height = min(max(CGFloat(h), 260), maxH)
            if abs(popover.contentSize.height - height) > 2 { popover.contentSize = NSSize(width: 460, height: height) }
            return
        }
        guard let body = message.body as? [String: Any], body["action"] as? String == "openDoc",
              let project = body["project"] as? String, let path = body["path"] as? String,
              let base = panelURL(), var parts = URLComponents(url: base, resolvingAgainstBaseURL: false) else { return }
        // Encode each value exactly once, like JS encodeURIComponent ("+" too: URLSearchParams reads it as a space).
        var safe = CharacterSet.alphanumerics
        safe.insert(charactersIn: "-._~")
        let enc = { (v: String) in v.addingPercentEncoding(withAllowedCharacters: safe) ?? v }
        parts.percentEncodedFragment = "p=\(enc(project))&doc=\(enc(path))&view=doc"
        if let url = parts.url {
            popover.performClose(nil)
            openWindow(url, title: (path as NSString).lastPathComponent, size: NSSize(width: 900, height: 860))
        }
    }

    private func openWindow(_ url: URL, title: String, size: NSSize) {
        let window = NSWindow(contentRect: NSRect(origin: .zero, size: size),
                              styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = title
        window.isReleasedWhenClosed = false
        window.delegate = self
        let view = makeWebView(NSRect(origin: .zero, size: size))
        window.contentView = view
        view.load(URLRequest(url: url))
        window.center()
        windows.append(window)
        NSApp.setActivationPolicy(.regular)  // while a window is open: Dock icon and Cmd-Tab, so it can't get lost
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func windowWillClose(_ notification: Notification) {
        guard let window = notification.object as? NSWindow else { return }
        (window.contentView as? WKWebView)?.configuration.userContentController.removeScriptMessageHandler(forName: "forthmark")
        windows.removeAll { $0 === window }
        if windows.isEmpty { NSApp.setActivationPolicy(.accessory) }  // back to menu bar only
    }

    @objc private func openPanelWindowFromMenu() { openPanelWindow(newProject: false) }

    private func openPanelWindow(newProject: Bool = false) {
        ensureServer { [weak self] in
            guard let self, let base = self.panelURL() else { return }
            self.popover.performClose(nil)
            var parts = URLComponents(url: base, resolvingAgainstBaseURL: false)
            if newProject { parts?.fragment = "newproj=1" }  // the window opens the new-project form
            if let existing = self.windows.first(where: { $0.title == "Forthmark" }) {
                if newProject, let url = parts?.url, let view = existing.contentView as? WKWebView { view.load(URLRequest(url: url)) }
                existing.makeKeyAndOrderFront(nil)
                return NSApp.activate(ignoringOtherApps: true)
            }
            self.openWindow(parts?.url ?? base, title: "Forthmark", size: NSSize(width: 1320, height: 900))
        }
    }

    private func togglePopover() {
        if popover.isShown { return popover.performClose(nil) }
        ensureServer { [weak self] in
            guard let self, let button = self.statusItem.button else { return }
            if self.webView.url == nil { self.loadPanel() }
            self.popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
            // A status-item popover sits above the input method's candidate window, hiding it while typing
            // Chinese; one notch lower (still above normal windows) lets the candidates show on top.
            self.popover.contentViewController?.view.window?.level = .floating
            NSApp.activate(ignoringOtherApps: true)
        }
    }

    @objc private func openInBrowser() { ensureServer { [weak self] in if let u = self?.panelURL() { NSWorkspace.shared.open(u) } } }
    @objc private func refreshAll() { refreshBadge(); webView.reload() }
    @objc private func quit() { NSApp.terminate(nil) }

    @objc private func toggleLoginItem() {
        let service = SMAppService.mainApp
        do {
            if service.status == .enabled { try service.unregister() } else { try service.register() }
        } catch {
            alert(L("开机自启没有设置成功", "Couldn't set launch at login"), error.localizedDescription)
        }
        if service.status == .requiresApproval { SMAppService.openSystemSettingsLoginItems() }
    }

    // MARK: notifications

    private func checkNotifications() {
        api("/api/notify") { data in
            guard let data, let items = try? JSONSerialization.jsonObject(with: data) as? [[String: String]] else { return }
            for item in items { self.post(title: item["title"] ?? "Forthmark", body: item["body"] ?? "") }
        }
    }

    private func post(title: String, body: String) {
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil))
    }

    @objc private func testNotification() {
        UNUserNotificationCenter.current().getNotificationSettings { settings in
            DispatchQueue.main.async {
                if settings.authorizationStatus == .authorized || settings.authorizationStatus == .provisional {
                    self.post(title: "Forthmark", body: L("通知正常：卡住的事会在这里提醒你。", "Notifications work: blocked items will be flagged here."))
                } else {
                    self.alert(L("通知还没有被允许", "Notifications aren't allowed yet"), L("请在 系统设置 → 通知 → Forthmark 里打开「允许通知」。", "Turn on Allow Notifications in System Settings → Notifications → Forthmark."))
                }
            }
        }
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                withCompletionHandler done: @escaping (UNNotificationPresentationOptions) -> Void) {
        done([.banner, .list])
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                withCompletionHandler done: @escaping () -> Void) {
        DispatchQueue.main.async { self.loadPanel(); self.togglePopover() }
        done()
    }

    // MARK: the panel's alert / confirm / prompt (it uses them for decisions and pauses)

    private func modal(_ run: () -> Void) {
        popover.behavior = .applicationDefined  // keep the popover open while the dialog is up
        run()
        popover.behavior = .transient
    }

    private func alert(_ title: String, _ text: String) {
        let a = NSAlert()
        a.messageText = title
        a.informativeText = text
        modal { a.runModal() }
    }

    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        alert(message, "")
        completionHandler()
    }

    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let a = NSAlert()
        a.messageText = message
        a.addButton(withTitle: L("确定", "OK"))
        a.addButton(withTitle: L("取消", "Cancel"))
        var ok = false
        modal { ok = a.runModal() == .alertFirstButtonReturn }
        completionHandler(ok)
    }

    func webView(_ webView: WKWebView, runJavaScriptTextInputPanelWithPrompt prompt: String, defaultText: String?,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (String?) -> Void) {
        let a = NSAlert()
        a.messageText = prompt
        a.addButton(withTitle: L("确定", "OK"))
        a.addButton(withTitle: L("取消", "Cancel"))
        let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 320, height: 24))
        field.stringValue = defaultText ?? ""
        a.accessoryView = field
        a.window.initialFirstResponder = field
        var result: String?
        modal { result = a.runModal() == .alertFirstButtonReturn ? field.stringValue : nil }
        completionHandler(result)
    }

    // Links that would open a new window (external links in previewed docs) go to the browser.
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        // Web links only: a previewed doc must not be able to open local files, apps or custom URL schemes.
        if let url = navigationAction.request.url, ["http", "https", "mailto"].contains(url.scheme?.lowercased() ?? "") {
            NSWorkspace.shared.open(url)
        }
        return nil
    }
}

/// The data directory, the same rule as forthmark.py: $FORTHMARK_HOME (e.g. demo data), else ~/.forthmark.
/// The local service it starts inherits the environment, so both look at the same place.
let forthmarkHome: String = {
    if let env = ProcessInfo.processInfo.environment["FORTHMARK_HOME"], !env.isEmpty {
        return (env as NSString).expandingTildeInPath
    }
    return (NSHomeDirectory() as NSString).appendingPathComponent(".forthmark")
}()

/// Interface language, the same rule as forthmark.py: config.json "lang", else the system language
/// (as forthmark.py cached it, else macOS's own preference).
let uiIsEnglish: Bool = {
    let home = forthmarkHome
    if let data = FileManager.default.contents(atPath: (home as NSString).appendingPathComponent("config.json")),
       let cfg = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
       let lang = cfg["lang"] as? String, lang == "zh" || lang == "en" {
        return lang == "en"
    }
    if let cached = try? String(contentsOfFile: (home as NSString).appendingPathComponent("lang.cache"), encoding: .utf8) {
        return cached.trimmingCharacters(in: .whitespacesAndNewlines) == "en"
    }
    return !(Locale.preferredLanguages.first ?? "en").hasPrefix("zh")
}()

func L(_ zh: String, _ en: String) -> String { uiIsEnglish ? en : zh }

/// The Forthmark mark (assets/logo.svg, a 128 × 104 grid), drawn in code so the menu bar gets a crisp
/// template image at any scale that follows light/dark mode. y points down, as in the SVG.
func forthmarkTemplateImage(height: CGFloat) -> NSImage {
    let shapes: [[(CGFloat, CGFloat)]] = [
        [(0, 0), (20, 0), (20, 32), (0, 32)],
        [(0, 44), (20, 44), (20, 76), (0, 76)],
        [(0, 88), (12, 88), (20, 96), (12, 104), (0, 104)],
        [(32, 0), (112, 0), (128, 16), (112, 32), (32, 32)],
        [(32, 44), (88, 44), (104, 60), (88, 76), (32, 76)],
    ]
    let inset: CGFloat = 1, scale = (height - inset * 2) / 104
    let size = NSSize(width: (128 * scale + inset * 2).rounded(.up), height: height)
    let image = NSImage(size: size, flipped: true) { _ in
        NSColor.black.setFill()
        for shape in shapes {
            let path = NSBezierPath()
            for (i, (x, y)) in shape.enumerated() {
                let pt = NSPoint(x: inset + x * scale, y: inset + y * scale)
                if i == 0 { path.move(to: pt) } else { path.line(to: pt) }
            }
            path.close()
            path.fill()
        }
        return true
    }
    image.isTemplate = true
    image.accessibilityDescription = "Forthmark"
    return image
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)  // menu bar only, no Dock icon
app.run()
