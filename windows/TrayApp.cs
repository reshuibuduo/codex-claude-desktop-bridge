using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

static class Program {
    internal static readonly string Root = AppDomain.CurrentDomain.BaseDirectory;
    internal static string DataDir { get { return Environment.GetEnvironmentVariable("CODEX_CLAUDE_BRIDGE_DATA") ??
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "CodexClaudeBridge"); } }
    internal static string Config { get { return Path.Combine(DataDir, "config.json"); } }
    internal static string Python { get { return Path.Combine(Root, "Resources", "python", "python.exe"); } }
    internal static string Script(string name) { return Path.Combine(Root, "Resources", "runtime", "bridge", name); }
    internal static Dictionary<string, object> Read(string path) {
        try { return new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(File.ReadAllText(path, Encoding.UTF8)); }
        catch { return new Dictionary<string, object>(); }
    }
    internal static string Str(Dictionary<string, object> obj, string key) {
        object value; return obj.TryGetValue(key, out value) ? Convert.ToString(value) : "";
    }
    internal static string State(bool enabled, string phase, double stamp, double now) {
        if (!enabled) return "已暂停 · 不接收新故障";
        switch (phase) {
            case "WAITING_FOR_NEW_FAILURE": return now - stamp < 20 ? "等待故障 · Claude 桌面已待命" : "待命连接已过期 · 请重新打开待命会话";
            case "HANDOFF_DELIVERED": return "已交接 · Claude 桌面正在接续";
            case "ACCEPTANCE_PASSED": return "验收通过 · 请查看测试记录";
            case "COMPLETED_REPORTED": return "Claude 已报告完成 · 请查看测试记录";
            case "SOURCE_FAILURE_NOT_ELIGIBLE": return "故障需检查 · 未自动转接";
            case "REVIEW_PREVIOUS_HANDOFF": case "COMPLETION_CONFLICT": return "存在待核对的接续 · 已停止自动交接";
            case "ERROR": return "连接异常 · 查看记录后重新待命";
            default: return "已启用 · 等待 Claude 建立待命连接";
        }
    }
    // CommandLineToArgvW quoting, never a shell command. Handles spaces, quotes and final backslashes.
    internal static string Quote(string value) {
        var result = new StringBuilder("\""); int slashes = 0;
        foreach (char c in value) {
            if (c == '\\') { slashes++; continue; }
            if (c == '"') { result.Append('\\', slashes * 2 + 1); result.Append(c); }
            else { result.Append('\\', slashes); result.Append(c); }
            slashes = 0;
        }
        result.Append('\\', slashes * 2); return result.Append('"').ToString();
    }
    internal static Tuple<int, string> PythonRun(string[] args) {
        if (!File.Exists(Python)) return Tuple.Create(1, "BUNDLE_RUNTIME_ERROR: embedded Python missing");
        try {
            var info = new ProcessStartInfo(Python, String.Join(" ", args.Select(Quote))) {
                UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8,
                WorkingDirectory = Root
            };
            using (var p = Process.Start(info)) {
                var stdout = p.StandardOutput.ReadToEndAsync(); var stderr = p.StandardError.ReadToEndAsync();
                if (!p.WaitForExit(30000)) { p.Kill(); p.WaitForExit(); return Tuple.Create(1, "HELPER_TIMEOUT"); }
                return Tuple.Create(p.ExitCode, stdout.Result + stderr.Result);
            }
        } catch (Exception e) { return Tuple.Create(1, "BUNDLE_RUNTIME_ERROR: " + e.Message); }
    }
    internal static Tuple<int, string> Helper(params string[] args) {
        return PythonRun(new [] { "-E", "-s", "-B", Script("desktop_setup.py"), "--config", Config }.Concat(args).ToArray());
    }
    static void Check(bool condition) { if (!condition) throw new Exception("native self test failed"); }
    [STAThread]
    static int Main(string[] args) {
        try {
            if (args.Contains("--self-test")) {
                Check(State(false,"WAITING_FOR_NEW_FAILURE",100,100).StartsWith("已暂停"));
                Check(State(true,"WAITING_FOR_NEW_FAILURE",100,105).StartsWith("等待故障"));
                Check(State(true,"WAITING_FOR_NEW_FAILURE",100,130).StartsWith("待命连接已过期"));
                Check(State(true,"HANDOFF_DELIVERED",0,100).StartsWith("已交接"));
                Check(State(true,"REVIEW_PREVIOUS_HANDOFF",0,100).StartsWith("存在待核对"));
                Check(State(true,"NO_STANDBY",0,100).StartsWith("已启用"));
                Check(State(true,"SOURCE_FAILURE_NOT_ELIGIBLE",0,100).StartsWith("故障需检查"));
                Check(Quote("a b") == "\"a b\""); Check(Quote("C:\\space dir\\") == "\"C:\\space dir\\\\\"");
                Check(Quote("a\"b") == "\"a\\\"b\"");
                Console.WriteLine("TRAY_SELF_TEST_OK checks=10"); return 0;
            }
            if (args.Contains("--bundle-self-test")) {
                var result = PythonRun(new [] { "-E", "-s", "-B", Script("bundle_smoke.py") });
                Console.Write(result.Item2); return result.Item1;
            }
            if (args.Contains("--pause")) {
                if (!File.Exists(Config)) return 0;
                var result = Helper("pause"); Console.Write(result.Item2); return result.Item1;
            }
            Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
            bool created;
            string sid = System.Security.Principal.WindowsIdentity.GetCurrent().User.Value;
            using (var mutex = new Mutex(true, "Local\\CodexClaudeBridge-" + sid, out created)) {
                if (!created) { MessageBox.Show("接续软件已经运行，请从系统托盘打开控制面板。", "Codex Claude Bridge"); return 0; }
                using (var form = new BridgeForm(args.Contains("--ui-smoke-test"))) { Application.Run(form); }
            }
            return 0;
        } catch (Exception e) { Console.Error.WriteLine(e.ToString()); return 1; }
    }
}

sealed class BridgeForm : Form {
    readonly NotifyIcon tray = new NotifyIcon();
    readonly ToolStripMenuItem phaseItem = new ToolStripMenuItem("已暂停");
    readonly System.Windows.Forms.Timer timer = new System.Windows.Forms.Timer();
    readonly TextBox thread = new TextBox(), cwd = new TextBox();
    readonly Label banner = new Label(), detail = new Label(), feedback = new Label();
    readonly bool smoke;
    bool busy, quitting;
    internal BridgeForm(bool uiSmoke) {
        smoke = uiSmoke; Text = "Codex → Claude · 桌面接续";
        Font = new Font("Segoe UI", 10); AutoScaleMode = AutoScaleMode.Dpi;
        ClientSize = new Size(760, 720); MinimumSize = new Size(700, 600); AutoScroll = true;
        StartPosition = FormStartPosition.CenterScreen; Icon = SystemIcons.Application;
        var table = new TableLayoutPanel { Dock = DockStyle.Top, AutoSize = true, Padding = new Padding(24), ColumnCount = 1 };
        table.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100)); Controls.Add(table);
        Add(table, new Label { Text = "Codex → Claude", Font = new Font(Font.FontFamily, 23, FontStyle.Bold), Height = 46 });
        Add(table, new Label { Text = "模型故障后，在已登录的 Claude 桌面 Code 中接着做。", Height = 28 });
        banner.Font = new Font(Font, FontStyle.Bold); banner.Height = 32; Add(table, banner);
        detail.Height = 40; Add(table, detail);
        Add(table, new Label { Text = "Codex 对话 ID（一次绑定一个本机对话）", Height = 25 });
        thread.AccessibleName = "Codex 对话 ID"; Add(table, thread);
        Add(table, new Label { Text = "同一项目目录（原生 Windows 路径；不支持 WSL 会话）", Height = 27 });
        var folderRow = new TableLayoutPanel { ColumnCount = 2, Height = 36, Dock = DockStyle.Fill };
        folderRow.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100)); folderRow.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 88));
        cwd.AccessibleName = "项目目录"; cwd.Dock = DockStyle.Fill; folderRow.Controls.Add(cwd);
        var browse = Button("选择…", delegate { using (var dialog = new FolderBrowserDialog()) { if (dialog.ShowDialog(this) == DialogResult.OK) cwd.Text = dialog.SelectedPath; } });
        folderRow.Controls.Add(browse); Add(table, folderRow);
        var row = new FlowLayoutPanel { Height = 42, Dock = DockStyle.Fill };
        row.Controls.Add(Button("1. 保存绑定", async delegate { await Action(new [] { "bind", "--thread", thread.Text.Trim(), "--cwd", cwd.Text.Trim() }, "绑定已保存；下一步打开 Claude 待命。"); }));
        row.Controls.Add(Button("2. 打开 Claude 待命", async delegate { await Standby(); }));
        row.Controls.Add(Button("暂停", async delegate { await Action(new [] { "pause" }, "已暂停新接续；正在执行的 Claude 任务保持原状态。"); }));
        row.Controls.Add(Button("复制待命提示", async delegate { await CopyPrompt(); })); Add(table, row);
        Add(table, new Label { Text = "首次打开后，先在 Claude“环境”中确认实际工作目录，再发送提示。\n显示“等待故障”才算接通。接续期间不要同时重试源任务。关闭此窗口会收起到系统托盘。", Height = 65 });
        feedback.Height = 70; Add(table, feedback);
        var footer = new FlowLayoutPanel { Height = 40, Dock = DockStyle.Fill };
        footer.Controls.Add(Button("使用说明", delegate { Open("https://github.com/reshuibuduo/codex-claude-desktop-bridge#readme"); }));
        footer.Controls.Add(Button("查看运行目录", delegate { Directory.CreateDirectory(Program.DataDir); Open(Program.DataDir); }));
        footer.Controls.Add(Button("退出并暂停", async delegate { await Quit(); })); Add(table, footer);
        var menu = new ContextMenuStrip(); phaseItem.Enabled = false; menu.Items.Add(phaseItem); menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add("控制面板…", null, delegate { Show(); WindowState = FormWindowState.Normal; Activate(); });
        menu.Items.Add("暂停新接续", null, async delegate { await Action(new [] { "pause" }, "已暂停新接续。"); });
        menu.Items.Add("退出并暂停", null, async delegate { await Quit(); });
        tray.Icon = Icon; tray.Text = "Codex → Claude 桌面接续"; tray.ContextMenuStrip = menu; tray.Visible = true;
        tray.DoubleClick += delegate { Show(); Activate(); };
        var cfg = Program.Read(Program.Config); thread.Text = Program.Str(cfg,"thread_id"); cwd.Text = Program.Str(cfg,"cwd");
        RefreshStatus(); timer.Interval = 2000; timer.Tick += delegate { RefreshStatus(); }; timer.Start();
        Shown += delegate {
            if (smoke) { CheckUI(); quitting = true; Close(); }
        };
        FormClosing += delegate(object sender, FormClosingEventArgs e) { if (!quitting && e.CloseReason == CloseReason.UserClosing) { e.Cancel = true; Hide(); } };
    }
    static void Add(TableLayoutPanel parent, Control control) { control.Dock = DockStyle.Fill; parent.Controls.Add(control); }
    static Button Button(string text, EventHandler click) { var b = new Button { Text = text, AutoSize = true, Height = 32 }; b.Click += click; return b; }
    void CheckUI() {
        if (!Visible || !tray.Visible || tray.ContextMenuStrip.Items.Count < 4) throw new Exception("UI smoke failed");
        string capture = Environment.GetEnvironmentVariable("CODEX_CLAUDE_BRIDGE_UI_CAPTURE");
        if (!String.IsNullOrEmpty(capture)) {
            using (var bitmap = new Bitmap(Width, Height)) {
                DrawToBitmap(bitmap, new Rectangle(0, 0, Width, Height));
                bitmap.Save(capture, System.Drawing.Imaging.ImageFormat.Png);
            }
        }
        Console.WriteLine("UI_STARTUP_OK window=visible tray=ready");
    }
    void RefreshStatus() {
        var cfg = Program.Read(Program.Config); string dir = Program.Str(cfg,"state_dir");
        var state = Program.Read(Path.Combine(dir, "desktop-status.json"));
        object flag; bool enabled = cfg.TryGetValue("enabled", out flag) && flag is bool && (bool)flag;
        double stamp; Double.TryParse(Program.Str(state,"time"), out stamp);
        string text = Program.State(enabled, Program.Str(state,"phase"), stamp, (DateTime.UtcNow - new DateTime(1970,1,1)).TotalSeconds);
        banner.Text = text; phaseItem.Text = text;
        detail.Text = "本机 Codex 命名管道 → 项目 MCP → Claude Desktop Code\n绑定：" + Program.Str(cfg,"thread_id");
    }
    async Task<Tuple<int,string>> Run(string[] args) {
        if (busy) return Tuple.Create(1, "正在处理上一个操作。");
        busy = true; feedback.Text = "正在处理…";
        try { return await Task.Run(() => Program.Helper(args)); }
        finally { busy = false; RefreshStatus(); }
    }
    async Task Action(string[] args, string message) {
        var r = await Run(args); feedback.Text = r.Item1 == 0 ? message : Tail(r.Item2);
    }
    static string Tail(string text) { return text.Length > 450 ? text.Substring(text.Length - 450) : text; }
    async Task<string> Prompt() {
        var r = await Run(new [] { "prompt" });
        if (r.Item1 != 0) { feedback.Text = Tail(r.Item2); return null; }
        return Program.Str(new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(r.Item2), "prompt");
    }
    async Task CopyPrompt() { var prompt = await Prompt(); if (prompt != null) { Clipboard.SetText(prompt); feedback.Text = "待命提示已复制；在已绑定目录的 Claude Code 会话中发送。"; } }
    async Task Standby() {
        var r = await Run(new [] { "enable" }); if (r.Item1 != 0) { feedback.Text = Tail(r.Item2); return; }
        var prompt = await Prompt(); if (prompt == null) return;
        string folder = Program.Str(Program.Read(Program.Config), "cwd");
        if (Open("claude://code/new?q=" + Uri.EscapeDataString(prompt) + "&folder=" + Uri.EscapeDataString(folder)))
            feedback.Text = "已请求打开 Claude。请确认“环境”里的实际目录，再发送待命提示。若链接未打开，请使用“复制待命提示”。";
    }
    bool Open(string value) {
        try { Process.Start(new ProcessStartInfo(value) { UseShellExecute = true }); return true; }
        catch (Exception e) { feedback.Text = Tail(e.Message) + "\n请打开 Claude Code 的绑定目录，并使用复制待命提示。"; return false; }
    }
    async Task Quit() {
        if (busy) { feedback.Text = "请等待当前操作完成，再退出。"; return; }
        if (File.Exists(Program.Config)) { var r = await Run(new [] { "pause" }); if (r.Item1 != 0) { Show(); feedback.Text = Tail(r.Item2); return; } }
        quitting = true; Close();
    }
    protected override void Dispose(bool disposing) {
        if (disposing) { timer.Stop(); timer.Dispose(); tray.Visible = false; tray.Dispose(); }
        base.Dispose(disposing);
    }
}
