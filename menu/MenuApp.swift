import AppKit

func stateText(enabled: Bool, phase: String, stamp: Double, now: Double) -> String {
    if !enabled { return "已暂停 · 不接收新故障" }
    switch phase {
    case "WAITING_FOR_NEW_FAILURE": return now - stamp < 20 ? "等待故障 · Claude 桌面已待命" : "待命连接已过期 · 请重新打开待命会话"
    case "HANDOFF_DELIVERED": return "已交接 · Claude 桌面正在接续"
    case "ACCEPTANCE_PASSED": return "验收通过 · 6 项测试通过"
    case "COMPLETED_REPORTED": return "Claude 已报告完成 · 请查看测试记录"
    case "SOURCE_FAILURE_NOT_ELIGIBLE": return "故障需检查 · 未自动转接"
    case "REVIEW_PREVIOUS_HANDOFF", "COMPLETION_CONFLICT": return "存在待核对的接续 · 已停止自动交接"
    case "ERROR": return "连接异常 · 查看记录后重新待命"
    default: return "已启用 · 等待 Claude 建立待命连接"
    }
}
func readObject(_ url: URL) -> [String: Any] {
    guard let data = try? Data(contentsOf: url), let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return [:] }
    return obj
}

if CommandLine.arguments.contains("--self-test") {
    assert(stateText(enabled:false,phase:"WAITING_FOR_NEW_FAILURE",stamp:100,now:100).hasPrefix("已暂停"))
    assert(stateText(enabled:true,phase:"WAITING_FOR_NEW_FAILURE",stamp:100,now:105).hasPrefix("等待故障"))
    assert(stateText(enabled:true,phase:"WAITING_FOR_NEW_FAILURE",stamp:100,now:130).hasPrefix("待命连接已过期"))
    assert(stateText(enabled:true,phase:"HANDOFF_DELIVERED",stamp:100,now:105).hasPrefix("已交接"))
    assert(stateText(enabled:true,phase:"NO_STANDBY",stamp:0,now:100).hasPrefix("已启用"))
    assert(stateText(enabled:true,phase:"ACCEPTANCE_PASSED",stamp:0,now:100).hasPrefix("验收通过"))
    assert(stateText(enabled:true,phase:"REVIEW_PREVIOUS_HANDOFF",stamp:0,now:100).hasPrefix("存在待核对"))
    assert(stateText(enabled:true,phase:"SOURCE_FAILURE_NOT_ELIGIBLE",stamp:0,now:100).hasPrefix("故障需检查"))
    print("MENU_SELF_TEST_OK checks=8")
    exit(0)
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    var item: NSStatusItem!
    var window: NSWindow!
    var timer: Timer?
    var banner = NSTextField(labelWithString: "正在读取状态…")
    var detail = NSTextField(wrappingLabelWithString: "")
    var sourceField = NSTextField(string: "")
    var cwdField = NSTextField(string: "")
    var feedback = NSTextField(wrappingLabelWithString: "")
    var phaseItem: NSMenuItem!
    var busy = false
    var dataDir: URL {
        if let override = ProcessInfo.processInfo.environment["CODEX_CLAUDE_BRIDGE_DATA"] {
            return URL(fileURLWithPath:override, isDirectory:true)
        }
        return FileManager.default.urls(for:.applicationSupportDirectory, in:.userDomainMask)[0]
            .appendingPathComponent("CodexClaudeBridge", isDirectory:true)
    }
    var configURL: URL { dataDir.appendingPathComponent("config.json") }
    var runtime: URL { Bundle.main.resourceURL!.appendingPathComponent("runtime") }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        item.button?.image = NSImage(systemSymbolName:"arrow.triangle.2.circlepath", accessibilityDescription:"Codex Claude Bridge")
        item.button?.title = " 接续"
        item.button?.toolTip = "Codex → Claude 桌面接续"
        let menu = NSMenu()
        phaseItem = NSMenuItem(title:"已暂停",action:nil,keyEquivalent:"")
        menu.addItem(phaseItem); menu.addItem(.separator())
        for (title, action) in [("控制面板…",#selector(showPanel)),("暂停新接续",#selector(pause)),("使用说明",#selector(showEvidence)),("退出（暂停新接续）",#selector(quit))] {
            let entry=NSMenuItem(title:title,action:action,keyEquivalent:"");entry.target=self;menu.addItem(entry)
        }
        item.menu=menu
        buildWindow()
        let cfg=readObject(configURL)
        sourceField.stringValue=cfg["thread_id"] as? String ?? ""
        cwdField.stringValue=cfg["cwd"] as? String ?? ""
        refresh()
        timer=Timer.scheduledTimer(withTimeInterval:2,repeats:true) { [weak self] _ in self?.refresh() }
        showPanel()
    }
    func label(_ text:String, size:CGFloat=13, color:NSColor = .labelColor) -> NSTextField {
        let l=NSTextField(wrappingLabelWithString:text);l.font=NSFont.systemFont(ofSize:size);l.textColor=color;return l
    }
    func button(_ text:String, _ selector:Selector) -> NSButton {
        let b=NSButton(title:text,target:self,action:selector);b.bezelStyle = .rounded;return b
    }
    func buildWindow() {
        window=NSWindow(contentRect:NSRect(x:0,y:0,width:690,height:500),styleMask:[.titled,.closable,.miniaturizable],backing:.buffered,defer:false)
        window.title="Codex → Claude · 桌面接续";window.isReleasedWhenClosed=false;window.center()
        let content=window.contentView!
        let stack=NSStackView();stack.orientation = .vertical;stack.alignment = .leading;stack.spacing=14;stack.translatesAutoresizingMaskIntoConstraints=false
        content.addSubview(stack)
        NSLayoutConstraint.activate([stack.leadingAnchor.constraint(equalTo:content.leadingAnchor,constant:26),stack.trailingAnchor.constraint(equalTo:content.trailingAnchor,constant:-26),stack.topAnchor.constraint(equalTo:content.topAnchor,constant:24)])
        let title=label("Codex → Claude",size:24);title.font=NSFont.boldSystemFont(ofSize:24);stack.addArrangedSubview(title)
        stack.addArrangedSubview(label("模型故障后，在你已登录的 Claude 桌面 Code 中接着做。",color:.secondaryLabelColor))
        banner.font=NSFont.boldSystemFont(ofSize:15);stack.addArrangedSubview(banner)
        detail.textColor = .secondaryLabelColor;detail.font=NSFont.monospacedSystemFont(ofSize:11,weight:.regular);stack.addArrangedSubview(detail)
        stack.addArrangedSubview(label("Codex 对话 ID（一次绑定一个本机对话）",size:12,color:.secondaryLabelColor))
        sourceField.font=NSFont.monospacedSystemFont(ofSize:12,weight:.regular);sourceField.placeholderString="Codex conversation UUID";sourceField.setAccessibilityLabel("Codex 对话 ID")
        stack.addArrangedSubview(sourceField);sourceField.widthAnchor.constraint(equalTo:stack.widthAnchor).isActive=true
        stack.addArrangedSubview(label("同一项目目录",size:12,color:.secondaryLabelColor))
        cwdField.font=NSFont.systemFont(ofSize:12);cwdField.setAccessibilityLabel("项目目录");stack.addArrangedSubview(cwdField);cwdField.widthAnchor.constraint(equalTo:stack.widthAnchor).isActive=true
        let row=NSStackView(views:[button("1. 保存绑定",#selector(saveBinding)),button("2. 打开 Claude 待命",#selector(startStandby)),button("暂停",#selector(pause))]);row.spacing=9;stack.addArrangedSubview(row)
        stack.addArrangedSubview(label("首次打开后，请在 Claude“环境”中确认实际工作目录，再发送待命提示。状态变成“等待故障”才算接通。接续期间不要同时重试源任务；暂停仅停止新交接。",size:12,color:.secondaryLabelColor))
        feedback.font=NSFont.systemFont(ofSize:12);feedback.textColor = .secondaryLabelColor;stack.addArrangedSubview(feedback)
        let footer=NSStackView(views:[button("使用说明",#selector(showEvidence)),button("查看运行目录",#selector(showLogs))]);footer.spacing=10;stack.addArrangedSubview(footer)
    }
    @objc func showPanel() { window.makeKeyAndOrderFront(nil);NSApp.activate(ignoringOtherApps:true) }
    func refresh() {
        let cfg=readObject(configURL);let enabled=cfg["enabled"] as? Bool ?? false
        let stateDir=cfg["state_dir"] as? String ?? ""
        let status=stateDir.isEmpty ? [:] : readObject(URL(fileURLWithPath:stateDir).appendingPathComponent("desktop-status.json"))
        let phase=status["phase"] as? String ?? "NO_STANDBY"
        let text=stateText(enabled:enabled,phase:phase,stamp:status["time"] as? Double ?? 0,now:Date().timeIntervalSince1970)
        banner.stringValue=text;phaseItem.title=text
        banner.textColor = phase == "WAITING_FOR_NEW_FAILURE" && text.hasPrefix("等待故障") ? .systemGreen : .labelColor
        detail.stringValue="本机 Codex IPC → 项目 MCP → Claude Desktop Code\n绑定：\(cfg["thread_id"] as? String ?? "尚未配置")"
        item.button?.title = enabled && text.hasPrefix("等待故障") ? " 待命" : " 接续"
    }
    func runHelper(_ args:[String], finished:@escaping(Bool,String)->Void) {
        if busy { feedback.stringValue="正在处理上一个操作。";return };busy=true;feedback.stringValue="正在处理…"
        let script=runtime.appendingPathComponent("bridge/desktop_setup.py").path
        let config=configURL.path
        DispatchQueue.global(qos:.userInitiated).async {
            let process=Process();process.executableURL=URL(fileURLWithPath:"/usr/bin/python3");process.arguments=[script,"--config",config]+args
            let pipe=Pipe();process.standardOutput=pipe;process.standardError=pipe
            var text="";var success=false
            do {try process.run();let data=pipe.fileHandleForReading.readDataToEndOfFile();process.waitUntilExit();text=String(data:data,encoding:.utf8) ?? "";success=process.terminationStatus==0}
            catch {text=error.localizedDescription}
            let resultText=text;let resultSuccess=success
            DispatchQueue.main.async {self.busy=false;self.refresh();finished(resultSuccess,resultText)}
        }
    }
    @objc func saveBinding() {
        runHelper(["bind","--thread",sourceField.stringValue.trimmingCharacters(in:.whitespacesAndNewlines),"--cwd",cwdField.stringValue.trimmingCharacters(in:.whitespacesAndNewlines)]) { ok,text in
            self.feedback.stringValue=ok ? "绑定已保存，项目 MCP 已安装。原配置已备份；下一步打开 Claude 待命。" : "绑定未改变：\(text.suffix(350))"
        }
    }
    @objc func startStandby() {
        runHelper(["enable"]) { ok,text in
            guard ok else {self.feedback.stringValue=text;return}
            self.runHelper(["prompt"]) { ok,text in
                guard ok, let data=text.data(using:.utf8),let obj=try? JSONSerialization.jsonObject(with:data) as? [String:String],let prompt=obj["prompt"] else {self.feedback.stringValue=text;return}
                let cfg=readObject(self.configURL)
                var url=URLComponents();url.scheme="claude";url.host="code";url.path="/new"
                url.queryItems=[URLQueryItem(name:"q",value:prompt),URLQueryItem(name:"folder",value:cfg["cwd"] as? String ?? "")]
                if let value=url.url,NSWorkspace.shared.open(value) {
                    self.feedback.stringValue="已打开 Claude。请确认“环境”里的工作目录是绑定项目，再发送；仅显示文件夹标签不代表目录已绑定。"
                } else {self.feedback.stringValue="待命链接打开失败；请在 Claude Code 打开绑定目录并使用 STANDBY_PROMPT.txt。"}
            }
        }
    }
    @objc func pause() {runHelper(["pause"]) {ok,text in self.feedback.stringValue=ok ? "已暂停新接续。已在执行的 Claude 任务保持原状态。" : text}}
    @objc func showEvidence() {NSWorkspace.shared.open(URL(string:"https://github.com/reshuibuduo/codex-claude-desktop-bridge#readme")!)}
    @objc func showLogs() {NSWorkspace.shared.open(dataDir)}
    @objc func quit() {
        if !FileManager.default.fileExists(atPath:configURL.path) { NSApp.terminate(nil); return }
        runHelper(["pause"]) {ok,text in if ok {NSApp.terminate(nil)} else {self.feedback.stringValue=text;self.showPanel()}}}
}
let app=NSApplication.shared
let delegate=AppDelegate()
app.delegate=delegate
app.run()
