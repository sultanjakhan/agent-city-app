using System.Runtime.InteropServices;
using System.Text.Json;
using Microsoft.Win32.SafeHandles;

namespace AgentCityDesktop;

internal sealed record ProfileIdentity(string PanelIdentity, string ConfigIdentity)
{
    [StructLayout(LayoutKind.Sequential)]
    private struct Info
    {
        public uint Attributes;
        public System.Runtime.InteropServices.ComTypes.FILETIME Creation, Access, Write;
        public uint Volume, SizeHigh, SizeLow, Links, IndexHigh, IndexLow;
    }
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern SafeFileHandle CreateFileW(string path, uint access, uint share, IntPtr security, uint creation, uint flags, IntPtr template);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool GetFileInformationByHandle(SafeFileHandle handle, out Info info);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    private static extern uint GetDriveTypeW(string root);
    private static void LocalWithoutReparse(string path)
    {
        var root = Path.GetPathRoot(path)!;
        if (root.StartsWith("\\\\") || GetDriveTypeW(root) is not (2 or 3 or 6)) throw new InvalidDataException("Local profile required");
        var current = root;
        foreach (var part in path[root.Length..].Split(Path.DirectorySeparatorChar, StringSplitOptions.RemoveEmptyEntries))
        {
            current = Path.Combine(current, part);
            if ((File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0)
                throw new InvalidDataException("Profile aliases through reparse points refused");
        }
    }
    private static string Identity(string path, bool directory)
    {
        LocalWithoutReparse(path);
        using var handle = CreateFileW(path, 0x80, 7, IntPtr.Zero, 3, 0x02000000, IntPtr.Zero);
        if (handle.IsInvalid || !GetFileInformationByHandle(handle, out var info) || ((info.Attributes & 0x10) != 0) != directory)
            throw new InvalidDataException("Profile identity unavailable");
        return $"{info.Volume:x8}:{info.IndexHigh:x8}{info.IndexLow:x8}";
    }
    private static string PathValue(JsonElement value, string key, string fallback, string basis)
    {
        var text = value.TryGetProperty(key, out var property) ? property.GetString() : fallback;
        if (string.IsNullOrEmpty(text)) throw new InvalidDataException("Profile path required");
        if (text == "~" || text.StartsWith("~/") || text.StartsWith("~\\"))
            text = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), text.Length > 1 ? text[2..] : "");
        return Path.GetFullPath(text, basis);
    }
    public static ProfileIdentity Load(string config)
    {
        config = Path.GetFullPath(config);
        var configId = Identity(config, false); // Metadata only; no credentials/session reads.
        if (new FileInfo(config).Length > 65536) throw new InvalidDataException("Config limit");
        using var doc = JsonDocument.Parse(File.ReadAllText(config), new JsonDocumentOptions { MaxDepth = 16 });
        var value = doc.RootElement;
        string[] allowed = ["schemaVersion", "dataRoot", "panelDirectory", "skillsDirectory", "credentialsDirectory", "codexHome", "repositoryRoots", "cicadaSources", "skillInventoryRoots"];
        if (value.ValueKind != JsonValueKind.Object || !value.TryGetProperty("schemaVersion", out var version) || version.GetInt32() != 1)
            throw new InvalidDataException("Config schema");
        var seen = new HashSet<string>();
        foreach (var property in value.EnumerateObject())
            if (!allowed.Contains(property.Name) || !seen.Add(property.Name)) throw new InvalidDataException("Config fields");
        var basis = Path.GetDirectoryName(config)!;
        var data = PathValue(value, "dataRoot", "../agent-city-data", basis);
        var panel = PathValue(value, "panelDirectory", Path.Combine(data, "panel"), basis);
        var code = Path.GetFullPath(AppContext.BaseDirectory).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        if ((panel.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar).StartsWith(code, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("External profile required");
        // Existing directory required: never select/create an empty replacement profile.
        return new ProfileIdentity(Identity(panel, true), configId + "\n" + basis.ToUpperInvariant());
    }
}

internal static class InstancePolicy
{
    public static string FocusName(string scope, string configScope, bool localOnly) =>
        "Local\\AgentCityDesktopFocus-" + scope + "-" + configScope + "-" + (localOnly ? "local" : "normal");
    public static bool Signal(string scope, string configScope, bool localOnly, bool activate = true)
    {
        try { using var signal = EventWaitHandle.OpenExisting(FocusName(scope, configScope, localOnly)); return !activate || signal.Set(); }
        catch (WaitHandleCannotBeOpenedException) { return false; }
        catch (UnauthorizedAccessException) { return false; }
    }
}
