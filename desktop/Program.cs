using System.Diagnostics;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Runtime.InteropServices;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace AgentCityDesktop;

internal static class WirePolicy
{
    public static Uri Origin(int port, string host)
    {
        if (port is < 1 or > 65535 || !Regex.IsMatch(host, "^agent-city-[a-f0-9]{32}\\.localhost$"))
            throw new InvalidDataException("Invalid private readiness");
        return new Uri($"http://{host}:{port}/");
    }
    public static bool SameOrigin(string value, Uri? origin)
    {
        return origin != null && Uri.TryCreate(value, UriKind.Absolute, out var uri) &&
            uri.Scheme == origin.Scheme && uri.Host == origin.Host && uri.Port == origin.Port && uri.UserInfo == "";
    }
    public static string Capability(string value, Uri origin)
    {
        if (!SameOrigin(value, origin)) throw new InvalidDataException("Invalid private handoff");
        var uri = new Uri(value);
        if (uri.AbsolutePath != "/" || uri.Query != "" || !Regex.IsMatch(uri.Fragment, "^#owner-bootstrap=[A-Za-z0-9_-]{43}$"))
            throw new InvalidDataException("Invalid private handoff");
        return uri.Fragment[17..];
    }
    public static string Scope(string identity, string user)
    {
        var bytes = Encoding.UTF8.GetBytes(user + "\n" + identity.ToUpperInvariant());
        return Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant()[..32];
    }
}

internal sealed class PrivateBridge
{
    private Process? process;
    private readonly SemaphoreSlim gate = new(1);
    private int sequence;
    public Uri? Origin { get; private set; }
    public bool Retired { get; private set; }
    public bool Exited => process != null && process.HasExited;
    public bool CanControl => process != null && !Exited && !Retired;
    private static async Task<JsonElement> ReadFrame(StreamReader stream, CancellationToken ct, int maximum = 16384)
    {
        var text = new StringBuilder();
        var one = new char[1];
        while (text.Length < maximum)
        {
            if (await stream.ReadAsync(one.AsMemory(), ct) == 0) throw new EndOfStreamException();
            if (one[0] == '\n')
            {
                using var doc = JsonDocument.Parse(text.ToString());
                return doc.RootElement.Clone();
            }
            text.Append(one[0]);
        }
        throw new InvalidDataException("Private frame limit");
    }
    public async Task Start(string config, bool localOnly)
    {
        if (process != null) throw new InvalidOperationException("Already started");
        var info = new ProcessStartInfo(Path.Combine(AppContext.BaseDirectory, "backend", "AgentCityBackend.exe"))
        {
            WorkingDirectory = AppContext.BaseDirectory,
            UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true
        };
        info.ArgumentList.Add("--config"); info.ArgumentList.Add(config);
        info.ArgumentList.Add("--runtime"); info.ArgumentList.Add(localOnly ? "local-only" : "normal");
        process = Process.Start(info) ?? throw new InvalidOperationException("Backend unavailable");
        // Discard stderr, never copy exception details or a private response to logs.
        _ = Task.Run(async () => { var buffer = new char[1024]; while (await process.StandardError.ReadAsync(buffer) > 0) { } });
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(30));
        try
        {
            var reply = await ReadFrame(process.StandardOutput, timeout.Token);
            if (reply.GetProperty("version").GetInt32() != 1 || reply.GetProperty("kind").GetString() != "ready" ||
                reply.GetProperty("localOnly").GetBoolean() != localOnly) throw new InvalidDataException("Private readiness refused");
            Origin = WirePolicy.Origin(reply.GetProperty("port").GetInt32(), reply.GetProperty("ownerHost").GetString()!);
        }
        catch { Retire(); throw; }
    }
    public async Task<JsonElement> Command(string action, bool draftsClosed = false, int timeoutSeconds = 35, JsonElement? agentRequest = null)
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(timeoutSeconds));
        await gate.WaitAsync(timeout.Token);
        try
        {
            if (!CanControl) throw new InvalidOperationException("Private control unavailable");
            var id = ++sequence;
            var frame = agentRequest is null
                ? JsonSerializer.Serialize(new { version = 1, id, action, draftsClosed })
                : JsonSerializer.Serialize(new { version = 1, id, action, draftsClosed, request = agentRequest });
            if (Encoding.UTF8.GetByteCount(frame) >= (action == "agent-request" ? 64 * 1024 : 16384)) throw new InvalidDataException("Private frame limit");
            await process!.StandardInput.WriteLineAsync(frame.AsMemory(), timeout.Token);
            await process.StandardInput.FlushAsync(timeout.Token);
            var reply = await ReadFrame(process.StandardOutput, timeout.Token, action == "agent-request" ? 1024 * 1024 : 16384);
            if (reply.GetProperty("version").GetInt32() != 1 || reply.GetProperty("id").GetInt32() != id ||
                !reply.GetProperty("ok").GetBoolean()) throw new InvalidDataException("Private operation refused");
            var result = reply.GetProperty("result");
            if (action == "restart") Origin = WirePolicy.Origin(result.GetProperty("port").GetInt32(), result.GetProperty("ownerHost").GetString()!);
            return result;
        }
        catch { Retire(); throw; }
        finally { gate.Release(); }
    }
    public void Retire()
    {
        Retired = true;
        try { process?.StandardInput.Close(); } catch { }
        // Existing owner EOF path revokes, fences and drains. No PID kill/reuse.
    }
    public async Task WaitForExit()
    {
        if (process == null) return;
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(35));
        await process.WaitForExitAsync(timeout.Token);
    }
}

internal sealed class CityWindow : Form
{
    private readonly string config;
    private readonly bool localOnly;
    private readonly WebView2 view = new() { Dock = DockStyle.Fill };
    private readonly Label status = new() { Dock = DockStyle.Bottom, Height = 34, Padding = new Padding(10, 6, 0, 0) };
    private readonly ToolStripMenuItem recover = new(DesktopText.Recover);
    private readonly ToolStripMenuItem restart = new(DesktopText.Restart);
    private readonly ToolStripMenuItem revoke = new(DesktopText.Revoke);
    private readonly ToolStripMenuItem checkUpdates = new(DesktopText.CheckUpdates);
    private NativeWindowMenu? windowMenu;
    private AppUpdater? updater;
    private string? pendingUpdateJob, pendingUpdateVersion;
    private bool updateBusy;

    private PrivateBridge bridge = new();
    private AgentPipe? agentPipe;
    private CoreWebView2Environment? environment;
    private string? browserProfile;
    private bool browserExited, busy, closing, approvedClose, loaded, healthBusy;
    private long documentEpoch;
    private long completedEpoch = -1;
    private ulong localeNavigationId;
    private bool localeDocumentLoaded;
    private CoreWebView2? localeCore;
    private readonly DesktopLocale locale = new();
    private readonly System.Windows.Forms.Timer localeRefresh = new() { Interval = 1000 };
    private bool confirmationBusy;
    private string? draftFreezeId;
    private Task? localeReadTask;
    private long localeReadEpoch = -1;
    private string statusKey = nameof(DesktopText.Starting);
    private readonly BackendHealth backendHealth = new();
    private readonly System.Windows.Forms.Timer health = new() { Interval = 1000 };
    private readonly System.Windows.Forms.Timer placementSave = new() { Interval = 500 };
    private readonly WindowPlacementStore? placementStore;
    private WindowPlacement? windowPlacement;
    private readonly bool backgroundStart;
    protected override bool ShowWithoutActivation => backgroundStart;
    public CityWindow(string config, bool localOnly, bool backgroundStart = false, string? windowStateScope = null)
    {
        this.config = config; this.localOnly = localOnly;
        this.backgroundStart = backgroundStart;
        Text = "Agent City";
        using (var iconStream = typeof(CityWindow).Assembly.GetManifestResourceStream("AgentCity.Icon")!)
            Icon = new Icon(iconStream);
        Width = 1220; Height = 900; MinimumSize = new Size(760, 520);
        placementStore = WindowPlacementStore.ForScope(windowStateScope);
        var savedPlacement = placementStore?.Load();
        if (savedPlacement != null)
        {
            var areas = Screen.AllScreens.OrderByDescending(screen => screen.Primary).Select(screen => screen.WorkingArea).ToArray();
            windowPlacement = savedPlacement.Fit(areas);
            StartPosition = FormStartPosition.Manual;
            MinimumSize = new Size(Math.Min(760, windowPlacement.Width), Math.Min(520, windowPlacement.Height));
            Bounds = windowPlacement.Bounds;
            if (windowPlacement.Maximized) WindowState = FormWindowState.Maximized;
        }
        if (backgroundStart) WindowState = FormWindowState.Minimized;
        Controls.Add(view); Controls.Add(status);
        checkUpdates.Click += async (_, _) => await CheckForUpdates();
        SetStatus(nameof(DesktopText.Starting));
        recover.Click += async (_, _) => await Action(async () => await Bootstrap(false));
        revoke.Click += async (_, _) => await Action(async () => { await bridge.Command("revoke"); SetStatus(nameof(DesktopText.AccessRevoked)); });
        restart.Click += async (_, _) =>
        {
            if (!await ConfirmDrafts(nameof(DesktopText.RestartQuestion))) return;
            await Action(async () =>
            {
                if (bridge.CanControl) { var result = await bridge.Command("restart", true); await Navigate(result.GetProperty("url").GetString()!); }
                else
                {
                    if (!bridge.Exited) throw new InvalidOperationException("Previous child is draining");
                    bridge = new PrivateBridge(); await bridge.Start(config, localOnly); await Bootstrap(true);
                }
            });
        };
        Shown += async (_, _) =>
        {
            QueueWindowPlacement();
            await Action(Initialize);
            StartUpdates();
        };
        FormClosing += OnClosing;
        LocationChanged += (_, _) => QueueWindowPlacement();
        SizeChanged += (_, _) => QueueWindowPlacement();
        placementSave.Tick += (_, _) => SaveWindowPlacement();
        FormClosed += (_, _) => SaveWindowPlacement();
        health.Tick += async (_, _) => await ObserveBackend();
        // UI-only refresh: never issue locale reads through backend health/auth.
        localeRefresh.Tick += async (_, _) => { if (!busy && (localeReadTask == null || localeReadTask.IsCompleted)) await RefreshNativeLocale(); };
        Disposed += (_, _) => { localeRefresh.Dispose(); placementSave.Dispose(); };
    }
    private void QueueWindowPlacement()
    {
        // Minimize coordinates (including background startup) are never restored.
        // Keep the last normal/maximized state so focusing a minimized window
        // returns it to the state it had before it was minimized.
        if (!IsHandleCreated || IsDisposed || WindowState == FormWindowState.Minimized) return;
        var bounds = WindowState == FormWindowState.Normal ? Bounds : RestoreBounds;
        var placement = new WindowPlacement(bounds.X, bounds.Y, bounds.Width, bounds.Height, WindowState == FormWindowState.Maximized);
        if (!placement.Valid) return;
        windowPlacement = placement;
        placementSave.Stop(); placementSave.Start();
    }
    private void SaveWindowPlacement()
    {
        placementSave.Stop();
        if (windowPlacement != null) placementStore?.Save(windowPlacement);
    }
    private bool IsCurrentLocaleDocument(long epoch)
    {
        try
        {
            return !IsDisposed && !view.IsDisposed && !closing && localeCore != null &&
                ReferenceEquals(view.CoreWebView2, localeCore) &&
                localeDocumentLoaded &&
                epoch == documentEpoch && epoch == completedEpoch &&
                WirePolicy.SameOrigin(localeCore.Source, bridge.Origin);
        }
        catch { return false; }
    }

    // Unknown/unavailable locale keeps legacy RU copy; it does not select a
    // language or derive one from a private profile, OS culture or prior origin.
    private string NativeText(string key) =>
        locale.CopyFor(key, documentEpoch, IsCurrentLocaleDocument) ?? DesktopText.ForLanguage(key, "ru");

    private void RenderNativeCopy()
    {
        recover.Text = NativeText(nameof(DesktopText.Recover));
        restart.Text = NativeText(nameof(DesktopText.Restart));
        revoke.Text = NativeText(nameof(DesktopText.Revoke));
        checkUpdates.Text = NativeText(nameof(DesktopText.CheckUpdates));
        RenderStatus();
        windowMenu?.Refresh();
    }

    private void RenderStatus()
    {
        status.Text = NativeText(statusKey);
        if (pendingUpdateVersion != null)
            status.Text += "  |  " + string.Format(NativeText(nameof(DesktopText.UpdateReady)), pendingUpdateVersion);
    }

    private void SetStatus(string key)
    {
        statusKey = key;
        RenderStatus();
    }

    protected override void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e);
        windowMenu = new NativeWindowMenu(Handle, checkUpdates, recover, restart, revoke);
        windowMenu.Install();
    }

    protected override void WndProc(ref Message message)
    {
        if (message.Msg == 0x112 && windowMenu?.Dispatch(message.WParam) == true) return;
        if (message.Msg == 0x117)
        {
            checkUpdates.Enabled = !updateBusy && !closing;
            windowMenu?.Refresh();
            _ = RefreshNativeLocale();
        }
        base.WndProc(ref message);
    }

    private void StartUpdates()
    {
        if (updater != null || closing || IsDisposed) return;
        try
        {
            var root = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Agent City", "updates");
            Directory.CreateDirectory(root);
            var version = typeof(CityWindow).Assembly.GetName().Version!.ToString(3);
            updater = new AppUpdater(new AppUpdaterOptions(config, AppContext.BaseDirectory, root, version, UpdateTrust.PublicKeyPem));
            updater.StartPeriodic(result =>
            {
                if (!closing && !IsDisposed && IsHandleCreated)
                    try { BeginInvoke(() => AcceptUpdate(result)); } catch { }
                return Task.CompletedTask;
            });
        }
        catch { } // Update service failure never prevents opening the local app.
    }

    private void AcceptUpdate(UpdateCheckResult result)
    {
        if (closing || !result.Available || result.PendingJobPath == null) return;
        pendingUpdateJob = result.PendingJobPath;
        pendingUpdateVersion = result.Version;
        RenderStatus();
    }

    private async Task CheckForUpdates()
    {
        if (closing || updateBusy || updater == null) return;
        updateBusy = true; checkUpdates.Enabled = false;
        try
        {
            var result = await updater.CheckAndStageAsync();
            if (closing || IsDisposed) return;
            AcceptUpdate(result);
            if (!result.Available && pendingUpdateJob == null)
                SetStatus(result.Reason == "not-newer" ? nameof(DesktopText.UpToDate) : nameof(DesktopText.UpdateCheckUnavailable));
        }
        catch
        {
            if (!closing && !IsDisposed)
                SetStatus(nameof(DesktopText.UpdateCheckUnavailable));
        }
        finally { updateBusy = false; checkUpdates.Enabled = !closing; }
    }

    private async Task RefreshNativeLocale()
    {
        var pending = localeReadTask;
        if (pending != null && !pending.IsCompleted)
        {
            var pendingEpoch = localeReadEpoch;
            await pending;
            if (pendingEpoch == documentEpoch) return;
            if (localeReadTask != pending && localeReadTask != null) { await localeReadTask; return; }
        }
        if (busy || closing || !IsCurrentLocaleDocument(documentEpoch)) return;
        localeReadEpoch = documentEpoch;
        localeReadTask = ReadNativeLocale(documentEpoch);
        await localeReadTask;
    }

    private async Task ReadNativeLocale(long epoch)
    {
        try
        {
            if (await locale.ReadAsync(script => localeCore!.ExecuteScriptAsync(script), epoch, IsCurrentLocaleDocument))
                RenderNativeCopy();
        }
        catch { } // Locale presentation failure must not affect auth/runtime.
    }

    private async Task ObserveBackend()
    {
        if (busy || closing || healthBusy) return;
        healthBusy = true;
        try
        {
            if (!bridge.CanControl) backendHealth.LostControl();
            else backendHealth.Observe(await bridge.Command("status", timeoutSeconds: 3), localOnly);
            if (backendHealth.Unavailable) SetStatus(nameof(DesktopText.BackendUnavailable));
        }
        catch { backendHealth.LostControl(); SetStatus(nameof(DesktopText.BackendUnavailable)); }
        finally { healthBusy = false; }
        // Never close/reload/navigate here: the current DOM/drafts remain intact.
    }
    public void FocusOwnedWindow()
    {
        if (!Visible) Show();
        if (WindowState == FormWindowState.Minimized)
            WindowState = windowPlacement?.Maximized == true ? FormWindowState.Maximized : FormWindowState.Normal;
        NativeWindowMenu.Reveal(Handle);
        Activate(); BringToFront();
    }
    [DllImport("user32.dll")] private static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] private static extern IntPtr GetAncestor(IntPtr window, uint flags);
    private bool CanPresentDraftPrompt()
    {
        return WindowState != FormWindowState.Minimized && GetAncestor(GetForegroundWindow(), 2) == Handle;
    }
    private async Task ReleaseDraftFreeze()
    {
        var id = draftFreezeId; draftFreezeId = null;
        if (id != null && IsCurrentLocaleDocument(documentEpoch))
            try { await localeCore!.ExecuteScriptAsync(DesktopDrafts.Cancel(id)).WaitAsync(TimeSpan.FromSeconds(2)); } catch { }
    }
    private async Task<bool> ConfirmDrafts(string questionKey)
    {
        if (confirmationBusy || busy || closing || IsDisposed) return false;
        confirmationBusy = true;
        recover.Enabled = restart.Enabled = revoke.Enabled = false;
        var epoch = documentEpoch; var id = Guid.NewGuid().ToString("N"); var accepted = false;
        try
        {
            if (!IsCurrentLocaleDocument(epoch)) { SetStatus(nameof(DesktopText.CloseUnavailable)); return false; }
            var core = localeCore!;
            var flags = DesktopDrafts.Parse(await core.ExecuteScriptAsync(DesktopDrafts.Snapshot).WaitAsync(TimeSpan.FromSeconds(2)));
            if (!IsCurrentLocaleDocument(epoch)) return false;
            if (flags == null) { SetStatus(nameof(DesktopText.CloseUnavailable)); return false; }
            if (flags.Busy) { SetStatus(nameof(DesktopText.Saving)); return false; }
            var foreground = CanPresentDraftPrompt();
            if (flags.Dirty && !foreground) { SetStatus(nameof(DesktopText.DraftsPending)); return false; }
            var action = questionKey == nameof(DesktopText.RestartQuestion) ? "restart" : "close";
            var reply = await core.ExecuteScriptAsync(DesktopDrafts.Request(id, action, foreground)).WaitAsync(TimeSpan.FromSeconds(2));
            var until = DateTime.UtcNow.AddMinutes(2);
            while (IsCurrentLocaleDocument(epoch) && !busy && DateTime.UtcNow < until)
            {
                if (reply.Length > 64) return false;
                var result = JsonSerializer.Deserialize<string>(reply);
                if (result is "clean" or "discard") { draftFreezeId = id; accepted = true; return true; }
                if (result != "pending" || !CanPresentDraftPrompt()) { SetStatus(nameof(DesktopText.DraftsPending)); return false; }
                await Task.Delay(150);
                if (!IsCurrentLocaleDocument(epoch)) return false;
                reply = await core.ExecuteScriptAsync(DesktopDrafts.Poll(id)).WaitAsync(TimeSpan.FromSeconds(2));
            }
            return false;
        }
        catch { SetStatus(nameof(DesktopText.CloseUnavailable)); return false; }
        finally
        {
            if (!accepted && IsCurrentLocaleDocument(epoch))
                try { await localeCore!.ExecuteScriptAsync(DesktopDrafts.Cancel(id)).WaitAsync(TimeSpan.FromSeconds(2)); } catch { }
            confirmationBusy = false;
            recover.Enabled = restart.Enabled = revoke.Enabled = !busy && !closing && !IsDisposed;
        }
    }
    private async Task Action(Func<Task> operation)
    {
        if (busy || closing) return;
        busy = true; recover.Enabled = restart.Enabled = revoke.Enabled = false;
        try { await operation(); }
        catch { SetStatus(nameof(DesktopText.ActionFailed)); }
        finally { busy = false; await ReleaseDraftFreeze(); recover.Enabled = restart.Enabled = revoke.Enabled = true; }
    }
    private async Task Initialize()
    {
        // Agent access is owned by the host broker and remains independent of
        // renderer startup. A slow/unavailable WebView must not block reporting.
        await bridge.Start(config, localOnly);
        agentPipe = new AgentPipe(AgentPipe.Name(config), async request =>
            await bridge.Command("agent-request", agentRequest: request));
        agentPipe.Start();
        // Runtime only; no download/installer or system setting changes at launch.
        _ = CoreWebView2Environment.GetAvailableBrowserVersionString();
        browserProfile = Path.Combine(Path.GetTempPath(), "agentcity-desktop-browser-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(browserProfile);
        var options = new CoreWebView2EnvironmentOptions("--disable-background-networking --disable-sync --no-first-run");
        environment = await CoreWebView2Environment.CreateAsync(null, browserProfile, options);
        environment.BrowserProcessExited += (_, _) => browserExited = true;
        await view.EnsureCoreWebView2Async(environment);
        var core = view.CoreWebView2;
        localeCore = core;
        core.Settings.AreHostObjectsAllowed = false; core.Settings.IsWebMessageEnabled = false;
        core.Settings.AreDevToolsEnabled = false; core.Settings.AreDefaultContextMenusEnabled = false;
        core.Settings.AreBrowserAcceleratorKeysEnabled = false;
        core.NavigationStarting += (_, e) => { if (!WirePolicy.SameOrigin(e.Uri, bridge.Origin)) e.Cancel = true; else { documentEpoch++; completedEpoch = -1; localeNavigationId = e.NavigationId; locale.Invalidate(); } };
        core.NavigationCompleted += async (_, e) =>
        {
            if (e.NavigationId != localeNavigationId) return;
            localeDocumentLoaded = e.IsSuccess;
            if (!e.IsSuccess) { completedEpoch = -1; locale.Invalidate(); return; }
            completedEpoch = documentEpoch;
            await RefreshNativeLocale();
        };
        core.SourceChanged += async (_, e) =>
        {
            if (e.IsNewDocument) { localeDocumentLoaded = false; completedEpoch = -1; locale.Invalidate(); return; }
            // Fragment/history changes retain an already successful document.
            if (!localeDocumentLoaded) return;
            completedEpoch = documentEpoch;
            await RefreshNativeLocale();
        };
        core.FrameNavigationStarting += (_, e) => { if (!WirePolicy.SameOrigin(e.Uri, bridge.Origin)) e.Cancel = true; };
        core.NewWindowRequested += (_, e) => e.Handled = true;
        core.PermissionRequested += (_, e) => { e.State = CoreWebView2PermissionState.Deny; e.Handled = true; };
        core.DownloadStarting += (_, e) => { e.Cancel = true; e.Handled = true; };
        core.AddWebResourceRequestedFilter("*", CoreWebView2WebResourceContext.All);
        core.WebResourceRequested += (_, e) =>
        {
            if (!WirePolicy.SameOrigin(e.Request.Uri, bridge.Origin))
                e.Response = environment.CreateWebResourceResponse(new MemoryStream(), 403, "Blocked", "Content-Type: text/plain");
        };
        core.ProcessFailed += (_, _) => SetStatus(nameof(DesktopText.RendererUnavailable));
        await Bootstrap(true); health.Start(); localeRefresh.Start();
    }
    private async Task Navigate(string url)
    {
        _ = WirePolicy.Capability(url, bridge.Origin!);
        view.CoreWebView2.Navigate(url); loaded = true;
        SetStatus(localOnly ? nameof(DesktopText.LocalMode) : nameof(DesktopText.NormalMode));
        await Task.CompletedTask;
    }
    private async Task Bootstrap(bool fresh)
    {
        var epoch = documentEpoch;
        var result = await bridge.Command("bootstrap"); var url = result.GetProperty("url").GetString()!;
        var cap = WirePolicy.Capability(url, bridge.Origin!);
        if (fresh || !loaded) { await Navigate(url); return; }
        var operation = Guid.NewGuid().ToString("N");
        var timer = Stopwatch.StartNew();
        void DocumentCheck()
        {
            if (epoch != documentEpoch || !WirePolicy.SameOrigin(view.Source.AbsoluteUri, bridge.Origin))
                throw new InvalidOperationException("Recovery document changed");
        }
        try
        {
            DocumentCheck();
            var started = await view.CoreWebView2.ExecuteScriptAsync(RecoveryScripts.Start(operation, cap)).WaitAsync(TimeSpan.FromSeconds(2));
            if (RecoveryScripts.Primitive(started) != "started") throw new InvalidOperationException("Recovery refused");
            while (timer.Elapsed < TimeSpan.FromSeconds(15))
            {
                DocumentCheck();
                var encoded = await view.CoreWebView2.ExecuteScriptAsync(RecoveryScripts.Poll(operation)).WaitAsync(TimeSpan.FromSeconds(2));
                var state = RecoveryScripts.Primitive(encoded);
                if (state == "ok")
                {
                    DocumentCheck();
                    SetStatus(nameof(DesktopText.RecoveryReady));
                    return; // Explicit UI retry, not replay or DOM navigation.
                }
                if (state != "pending") throw new InvalidOperationException("Recovery refused");
                await Task.Delay(100);
            }
            throw new TimeoutException("Recovery deadline");
        }
        catch
        {
            // Ambiguous/late cookie exchange cannot silently retain new authority.
            try { await bridge.Command("revoke"); } catch { bridge.Retire(); }
            throw;
        }
        finally
        {
            if (epoch == documentEpoch && WirePolicy.SameOrigin(view.Source.AbsoluteUri, bridge.Origin))
                try { await view.CoreWebView2.ExecuteScriptAsync(RecoveryScripts.Clear(operation)).WaitAsync(TimeSpan.FromSeconds(2)); } catch { }
        }
    }
    private async void OnClosing(object? sender, FormClosingEventArgs e)
    {
        if (approvedClose) return;
        e.Cancel = true;
        if (busy || closing || (loaded && !await ConfirmDrafts(nameof(DesktopText.CloseQuestion)))) return;
        closing = true; recover.Enabled = restart.Enabled = revoke.Enabled = false;
        agentPipe?.Dispose(); agentPipe = null;
        try
        {
            if (bridge.CanControl) await bridge.Command("stop", true);
            else bridge.Retire();
            await bridge.WaitForExit();
            await StorageMigration.ApplyPrepared(config);
            health.Stop(); localeRefresh.Stop(); browserExited = false; view.Dispose();
            var until = DateTime.UtcNow.AddSeconds(10);
            while (environment != null && !browserExited && DateTime.UtcNow < until) await Task.Delay(50);
            if (browserExited && browserProfile != null) DeleteOwnProfile(browserProfile);
            // If renderer exit is unconfirmed, preserve temporary profile; no PID kill.
            updater?.Dispose(); updater = null;
            if (pendingUpdateJob != null)
            {
                try
                {
                    using var owner = Process.GetCurrentProcess();
                    var job = UpdateInstallJob.Load(pendingUpdateJob) with
                    {
                        OwnerPid = owner.Id.ToString(),
                        OwnerStartUtcTicks = owner.StartTime.ToUniversalTime().Ticks
                    };
                    using var helper = UpdateInstall.StartApply(job, AppContext.BaseDirectory);
                }
                catch { } // Preserve the installation and staged release for a later retry.
            }
            approvedClose = true; Close();
        }
        catch { closing = false; await ReleaseDraftFreeze(); SetStatus(nameof(DesktopText.DrainPending)); recover.Enabled = restart.Enabled = revoke.Enabled = true; }
    }
    private static void DeleteOwnProfile(string path)
    {
        if (!Directory.Exists(path)) return;
        var full = Path.GetFullPath(path); var temp = Path.GetFullPath(Path.GetTempPath());
        if (Path.GetDirectoryName(full) != temp.TrimEnd(Path.DirectorySeparatorChar) || !Path.GetFileName(full).StartsWith("agentcity-desktop-browser-")) return;
        if ((File.GetAttributes(full) & FileAttributes.ReparsePoint) != 0) return;
        // Refuse reparse points at any depth before recursive cleanup.
        var pending = new Stack<string>(); pending.Push(full);
        while (pending.Count > 0)
        {
            foreach (var child in Directory.EnumerateFileSystemEntries(pending.Pop()))
            {
                var attr = File.GetAttributes(child);
                if ((attr & FileAttributes.ReparsePoint) != 0) return;
                if ((attr & FileAttributes.Directory) != 0) pending.Push(child);
            }
        }
        try { Directory.Delete(full, true); } catch { }
    }
}

internal static class Program
{
    private static int SelfTest()
    {
        var origin = WirePolicy.Origin(12345, "agent-city-" + new string('a', 32) + ".localhost");
        if (!WirePolicy.SameOrigin(origin.ToString(), origin) || WirePolicy.SameOrigin("https://example.org/", origin) ||
            WirePolicy.SameOrigin("http://user@" + origin.Host + ":12345/", origin) || WirePolicy.SameOrigin("http://" + origin.Host + ":12346/", origin)) return 2;
        if (WirePolicy.Scope("C:/synthetic/profile.json", "synthetic-user") != WirePolicy.Scope("c:/SYNTHETIC/profile.json", "synthetic-user")) return 2;
        if (WirePolicy.Scope("C:/synthetic/profile.json", "synthetic-user") == WirePolicy.Scope("C:/synthetic/other.json", "synthetic-user")) return 2;
        if (RecoveryScripts.Primitive("\"pending\"") != "pending") return 2;
        try { RecoveryScripts.Primitive("{}"); return 2; } catch (InvalidDataException) { }
        var health = new BackendHealth();
        using (var live = JsonDocument.Parse("{\"backendAlive\":true,\"localOnly\":true}")) health.Observe(live.RootElement, true);
        if (health.Unavailable) return 2;
        using (var dead = JsonDocument.Parse("{\"backendAlive\":false,\"localOnly\":true}")) health.Observe(dead.RootElement, true);
        if (!health.Unavailable) return 2;
        if (DesktopText.Recover[0] != '\u0412' || DesktopText.Recover[1] != '\u043e' || DesktopText.Recover.Length != 19) return 2;
        var syntheticScope = Guid.NewGuid().ToString("N");
        using (var signal = new EventWaitHandle(false, EventResetMode.AutoReset, InstancePolicy.FocusName(syntheticScope, "synthetic-config", false)))
        {
            if (InstancePolicy.Signal(syntheticScope, "synthetic-config", true) || signal.WaitOne(0)) return 2;
            if (InstancePolicy.Signal(syntheticScope, "other-config", false) || signal.WaitOne(0)) return 2;
            if (!InstancePolicy.Signal(syntheticScope, "synthetic-config", false, false) || signal.WaitOne(0)) return 2;
            if (InstancePolicy.Signal(syntheticScope, "synthetic-config", true, false) || signal.WaitOne(0)) return 2;
            if (!InstancePolicy.Signal(syntheticScope, "synthetic-config", false) || !signal.WaitOne(100)) return 2;
        }
        var directory = Path.Combine(Path.GetTempPath(), "agentcity-desktop-policy-test-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        try
        {
            Directory.CreateDirectory(Path.Combine(directory, "panel"));
            var a = Path.Combine(directory, "a.json"); var b = Path.Combine(directory, "b.json");
            var data = "{\"schemaVersion\":1,\"panelDirectory\":\"panel\"}";
            File.WriteAllText(a, data); File.WriteAllText(b, data);
            var first = ProfileIdentity.Load(a); var second = ProfileIdentity.Load(b);
            if (first.PanelIdentity != second.PanelIdentity || first.ConfigIdentity == second.ConfigIdentity) return 2;
        }
        finally
        {
            // Only exact files/empty dirs this no-window selftest just created.
            File.Delete(Path.Combine(directory, "a.json")); File.Delete(Path.Combine(directory, "b.json"));
            Directory.Delete(Path.Combine(directory, "panel")); Directory.Delete(directory);
        }
        Console.WriteLine("{\"hostPolicySelfTest\":true,\"recoveryPrimitiveContract\":true,\"backendDeathObservation\":true,\"unicodeLabels\":true,\"modeSignalIsolation\":true,\"sharedPanelIdentity\":true,\"windowsOpened\":0,\"backendStarted\":false}");
        return 0;
    }
    [STAThread]
    private static int Main(string[] args)
    {
        if (args.SequenceEqual(new[] { "--self-test" })) return SelfTest();
        if (args.Length == 2 && args[0] == "--profile-check")
        {
            try { _ = ProfileIdentity.Load(args[1]); Console.WriteLine("{\"ok\":true,\"profileValid\":true,\"appStarted\":false}"); return 0; }
            catch (Exception error) { Console.WriteLine(JsonSerializer.Serialize(new { ok = false, error = error is InvalidDataException ? error.Message : error.GetType().Name, appStarted = false })); return 2; }
        }
        if (args.Length == 2 && args[0] == "--apply-update") return UpdateInstall.RunHelper(args[1], UpdateTrust.PublicKeyPem);
        if (args.Length == 2 && args[0] == "--agent-request-stdin") return AgentPipe.Client(args[1]).GetAwaiter().GetResult();
        if (args.Length == 1 && args[0] == "--agent-pipe-self-test") return AgentPipe.SelfTest().GetAwaiter().GetResult();
        bool localOnly = args.Contains("--local-only");
        bool background = args.Contains("--background");
        args = args.Where(a => a != "--local-only" && a != "--background").ToArray();
        string config;
        ProfileIdentity profile;
        try
        {
            if (args.Length == 2 && args[0] == "--config") config = Path.GetFullPath(args[1]);
            else if (args.Length == 0)
            {
                using var pointer = JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "desktop-profile.json")));
                config = Path.GetFullPath(pointer.RootElement.GetProperty("configFile").GetString()!);
            }
            else throw new InvalidDataException();
            profile = ProfileIdentity.Load(config);
        }
        catch { if (background) { Console.Error.WriteLine("Agent City profile unavailable"); return 2; } MessageBox.Show("\u041f\u0440\u043e\u0444\u0438\u043b\u044c \u043d\u0435 \u043d\u0430\u0441\u0442\u0440\u043e\u0435\u043d. \u0423\u0441\u0442\u0430\u043d\u043e\u0432\u043a\u0430 \u0434\u043e\u043b\u0436\u043d\u0430 \u044f\u0432\u043d\u043e \u0441\u043e\u0445\u0440\u0430\u043d\u0438\u0442\u044c \u0441\u0443\u0449\u0435\u0441\u0442\u0432\u0443\u044e\u0449\u0438\u0439 storage config; \u043d\u043e\u0432\u0430\u044f \u043f\u0430\u043f\u043a\u0430 \u0430\u0432\u0442\u043e\u043c\u0430\u0442\u0438\u0447\u0435\u0441\u043a\u0438 \u043d\u0435 \u0441\u043e\u0437\u0434\u0430\u0451\u0442\u0441\u044f.", "Agent City"); return 2; }
        var user = WindowsIdentity.GetCurrent().User?.Value ?? throw new InvalidOperationException();
        var scope = WirePolicy.Scope(profile.PanelIdentity, user);
        var configScope = WirePolicy.Scope(profile.ConfigIdentity, user);
        using var mutex = new Mutex(false, "Local\\AgentCityDesktop-" + scope);
        bool owned;
        try { owned = mutex.WaitOne(0); } catch (AbandonedMutexException) { owned = true; }
        if (!owned)
        {
            var until = Stopwatch.StartNew();
            do
            {
                if (InstancePolicy.Signal(scope, configScope, localOnly, !background)) return 0;
                Thread.Sleep(20);
            } while (until.Elapsed < TimeSpan.FromMilliseconds(500));
            if (background) return 3;
            MessageBox.Show(DesktopText.RuntimeMismatch, "Agent City");
            return 3; // No silent cross-mode/profile focus and no second backend.
        }
        try
        {
            using var focus = new EventWaitHandle(false, EventResetMode.AutoReset, InstancePolicy.FocusName(scope, configScope, localOnly));
            ApplicationConfiguration.Initialize();
            using var form = new CityWindow(config, localOnly, background, scope);
            var watcher = ThreadPool.RegisterWaitForSingleObject(focus, (_, _) =>
            {
                if (form.IsHandleCreated && !form.IsDisposed) try { form.BeginInvoke(form.FocusOwnedWindow); } catch { }
            }, null, Timeout.Infinite, false);
            try { Application.Run(form); } finally { watcher.Unregister(null); }
            return 0;
        }
        finally { mutex.ReleaseMutex(); }
    }
}
