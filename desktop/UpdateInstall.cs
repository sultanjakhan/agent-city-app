using System.Diagnostics;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.Win32;

namespace AgentCityDesktop;

/// <summary>Transaction job written by AppUpdater and consumed on graceful close.</summary>
public sealed record UpdateInstallJob(
    int SchemaVersion,
    string Version,
    string InstallRoot,
    string StagingRoot,
    string UpdaterRoot,
    string HelperRoot,
    string PackageSha256,
    string ManifestSha256,
    string? PackagePath = null,
    string? ManifestPath = null,
    string? SignaturePath = null,
    string? OwnerPid = null,
    long? OwnerStartUtcTicks = null)
{
    public const int CurrentSchemaVersion = 1;

    public void Save(string path)
    {
        if (SchemaVersion != CurrentSchemaVersion) throw new InvalidDataException("Unsupported update job");
        var full = UpdateInstall.ValidateFileTarget(path, Path.GetDirectoryName(path));
        Directory.CreateDirectory(Path.GetDirectoryName(full)!);
        var temporary = full + ".new-" + Guid.NewGuid().ToString("N");
        File.WriteAllText(temporary, JsonSerializer.Serialize(this, UpdateInstall.JsonOptions), new UTF8Encoding(false));
        File.Move(temporary, full, true);
    }

    public static UpdateInstallJob Load(string path)
    {
        var full = UpdateInstall.ValidateFileTarget(path, Path.GetDirectoryName(path));
        var value = JsonSerializer.Deserialize<UpdateInstallJob>(File.ReadAllText(full, Encoding.UTF8), UpdateInstall.JsonOptions)
            ?? throw new InvalidDataException("Invalid update job");
        if (value.SchemaVersion != CurrentSchemaVersion) throw new InvalidDataException("Unsupported update job");
        UpdateInstall.ValidateRoot(value.InstallRoot, mustExist: true);
        UpdateInstall.ValidateRoot(value.StagingRoot, mustExist: true);
        UpdateInstall.ValidateRoot(value.UpdaterRoot, mustExist: true);
        UpdateInstall.ValidateRoot(value.HelperRoot, mustExist: true);
        UpdateInstall.EnsureInside(value.StagingRoot, value.UpdaterRoot);
        UpdateInstall.EnsureInside(value.HelperRoot, value.UpdaterRoot);
        UpdateInstall.EnsureDisjoint(value.StagingRoot, value.InstallRoot);
        UpdateInstall.EnsureDisjoint(value.HelperRoot, value.StagingRoot);
        UpdateInstall.RequireSha256(value.PackageSha256);
        UpdateInstall.RequireSha256(value.ManifestSha256);
        if (value.PackagePath is null || value.ManifestPath is null || value.SignaturePath is null) throw new InvalidDataException("Incomplete update job");
        UpdateInstall.ValidateFileTarget(value.PackagePath, value.UpdaterRoot);
        UpdateInstall.ValidateFileTarget(value.ManifestPath, value.UpdaterRoot);
        UpdateInstall.ValidateFileTarget(value.SignaturePath, value.UpdaterRoot);
        if (!UpdateInstall.IsNewerVersion(value.Version, "0.0.0")) throw new InvalidDataException("Invalid update version");
        return value;
    }
}

public sealed record UpdateApplyResult(bool Applied, bool RolledBack, string? Version, string? FailureCode);

/// <summary>Safe update transaction. It never kills processes and never traverses reparse points.</summary>
public static class UpdateInstall
{
    internal static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        WriteIndented = false,
        AllowTrailingCommas = false,
        ReadCommentHandling = JsonCommentHandling.Disallow
    };

    private static readonly StringComparer FileComparer = StringComparer.OrdinalIgnoreCase;
    private static readonly string[] ProtectedNames =
        ["desktop-profile.json", "installation.json", "Uninstall-AgentCity.ps1", "updates-channel.json"];

    public static string PrepareHelperBundle(string installRoot, string updaterRoot)
    {
        var install = ValidateRoot(installRoot, true);
        var updater = ValidateRoot(updaterRoot, true);
        EnsureDisjoint(updater, install);
        var helper = Path.Combine(updater, "helper-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(helper);
        try
        {
            foreach (var file in EnumerateFilesNoReparse(install))
            {
                var relative = Path.GetRelativePath(install, file);
                if (!IsHelperFile(relative)) continue;
                var target = Path.Combine(helper, relative);
                EnsureRelativePath(relative);
                Directory.CreateDirectory(Path.GetDirectoryName(target)!);
                File.Copy(file, target, false);
            }
            var executable = Path.Combine(helper, "AgentCity.exe");
            if (!File.Exists(executable)) throw new InvalidDataException("Updater helper unavailable");
            return helper;
        }
        catch
        {
            TryDeleteTree(helper);
            throw;
        }
    }

    public static Process StartApply(UpdateInstallJob job, string currentInstallRoot)
    {
        var helper = PrepareHelperBundle(currentInstallRoot, job.UpdaterRoot);
        var helperJob = Path.Combine(job.UpdaterRoot, "apply-" + Guid.NewGuid().ToString("N") + ".json");
        var childJob = job with { HelperRoot = helper };
        childJob.Save(helperJob);
        var start = new ProcessStartInfo(Path.Combine(helper, "AgentCity.exe"))
        {
            WorkingDirectory = helper,
            UseShellExecute = false,
            CreateNoWindow = true
        };
        start.ArgumentList.Add("--apply-update");
        start.ArgumentList.Add(helperJob);
        return Process.Start(start) ?? throw new InvalidOperationException("Updater helper unavailable");
    }

    /// <summary>Entry point used by Program before opening the normal UI.</summary>
    public static int RunHelper(string jobPath, string publicKeyPem)
    {
        try
        {
            var job = UpdateInstallJob.Load(jobPath);
            var result = Apply(job, publicKeyPem);
            return result.Applied ? 0 : 2;
        }
        catch
        {
            // Details stay out of the product UI and command-line output.
            return 2;
        }
    }

    public static UpdateApplyResult Apply(UpdateInstallJob job) => ApplyCore(job, string.Empty);

    public static UpdateApplyResult Apply(UpdateInstallJob job, string publicKeyPem) => ApplyCore(job, publicKeyPem);

    private static UpdateApplyResult ApplyCore(UpdateInstallJob job, string publicKeyPem)
    {
        Mutex? applyLock = null;
        var ownsLock = false;
        try
        {
            applyLock = new Mutex(false, "Local\\AgentCityUpdateApply");
            try { ownsLock = applyLock.WaitOne(0); } catch (AbandonedMutexException) { ownsLock = true; }
            if (!ownsLock) return Failure(job, "apply-already-running");
            return ApplyLocked(job, publicKeyPem);
        }
        catch (PlatformNotSupportedException) { return ApplyLocked(job, publicKeyPem); }
        finally
        {
            if (ownsLock) try { applyLock?.ReleaseMutex(); } catch { }
            applyLock?.Dispose();
        }
    }

    private static UpdateApplyResult ApplyLocked(UpdateInstallJob job, string publicKeyPem)
    {
        var install = ValidateRoot(job.InstallRoot, true);
        var staging = ValidateRoot(job.StagingRoot, true);
        var updater = ValidateRoot(job.UpdaterRoot, true);
        var helper = ValidateRoot(job.HelperRoot, true);
        EnsureDisjoint(updater, install);
        EnsureInside(staging, updater);
        EnsureOutside(helper, install);
        EnsureInside(helper, updater);
        EnsureDisjoint(helper, staging);
        if (!File.Exists(Path.Combine(staging, "AgentCity.exe"))) return Failure(job, "missing-executable");
        using var stageLease = new ReadLease(staging, [job.PackagePath!, job.ManifestPath!, job.SignaturePath!]);
        if (!VerifyStagedPackage(job, staging, publicKeyPem)) return Failure(job, "staged-integrity");
        if (!CheckSelfTest(Path.Combine(staging, "AgentCity.exe"), staging)) return Failure(job, "health-check");
        if (!WaitForOwnerExit(job, TimeSpan.FromSeconds(60))) return Failure(job, "owner-timeout");
        // The owner drain can take time; re-read every staged artifact immediately before the rename.
        if (!VerifyStagedPackage(job, staging, publicKeyPem)) return Failure(job, "staged-integrity");

        CopyProtectedFiles(install, staging);
        // Windows cannot rename directories while descendants deny deletion.
        // Hold verified files through self-tests, then release only for the directory swap.
        stageLease.Dispose();
        var rollback = Path.Combine(updater, "rollback-" + DateTime.UtcNow.ToString("yyyyMMddHHmmss") + "-" + Guid.NewGuid().ToString("N"));
        var movedOld = false;
        var movedNew = false;
        try
        {
            Directory.Move(install, rollback); movedOld = true;
            Directory.Move(staging, install); movedNew = true;
            using (var installedLease = new ReadLease(install, [job.PackagePath!, job.ManifestPath!, job.SignaturePath!], publicFilesOnly: true))
            {
                if (!VerifyStagedPackage(job, install, publicKeyPem, allowLocalFiles: true)) throw new InvalidDataException("post-install-integrity");
                if (!CheckSelfTest(Path.Combine(install, "AgentCity.exe"), install)) throw new InvalidDataException("post-install-health");
            }
            // Keep the exact previous installation as a recoverable rollback point.
            UpdateReceiptAndRegistry(install, job);
            var applied = new UpdateApplyResult(true, false, job.Version, null);
            WriteLastUpdate(job, applied);
            return applied;
        }
        catch
        {
            var restored = false;
            try
            {
                if (movedNew && Directory.Exists(install)) Directory.Move(install, Path.Combine(updater, "failed-" + Guid.NewGuid().ToString("N")));
                if (movedOld && !Directory.Exists(install)) { Directory.Move(rollback, install); restored = true; }
            }
            catch { }
            return Failure(job, restored ? "apply-failed" : "rollback-failed", restored);
        }
    }

    private static UpdateApplyResult Failure(UpdateInstallJob job, string reason, bool rollback = false) =>
        WriteAndReturnFailure(job, new(false, rollback, job.Version, reason));

    private static UpdateApplyResult WriteAndReturnFailure(UpdateInstallJob job, UpdateApplyResult result)
    {
        WriteLastUpdate(job, result);
        return result;
    }

    private static void WriteLastUpdate(UpdateInstallJob job, UpdateApplyResult result)
    {
        try
        {
            var root = ValidateRoot(job.UpdaterRoot, true);
            var path = Path.Combine(root, "last-update.json");
            var temporary = path + ".new-" + Guid.NewGuid().ToString("N");
            File.WriteAllText(temporary, JsonSerializer.Serialize(new
            {
                schemaVersion = 1,
                applied = result.Applied,
                rolledBack = result.RolledBack,
                version = result.Version,
                failureCode = result.FailureCode,
                completedAtUtc = DateTime.UtcNow
            }, JsonOptions), new UTF8Encoding(false));
            File.Move(temporary, path, true);
        }
        catch { }
    }

    private static void UpdateReceiptAndRegistry(string installRoot, UpdateInstallJob job)
    {
        try
        {
            var manifestPath = Path.Combine(installRoot, "build-manifest.json");
            using var document = JsonDocument.Parse(File.ReadAllText(manifestPath, Encoding.UTF8));
            var manifest = document.RootElement;
            var sourceVersion = manifest.TryGetProperty("applicationSourceVersion", out var version) ? version.GetString() : null;
            if (sourceVersion is null || !string.Equals(sourceVersion, job.Version, StringComparison.Ordinal)) throw new InvalidDataException("Version receipt mismatch");
            var sourceCommit = manifest.TryGetProperty("sourceCommit", out var commit) ? commit.GetString() : null;
            var receiptPath = Path.Combine(installRoot, "installation.json");
            if (File.Exists(receiptPath) && (File.GetAttributes(receiptPath) & FileAttributes.ReparsePoint) == 0)
            {
                var node = JsonNode.Parse(File.ReadAllText(receiptPath, Encoding.UTF8)) as JsonObject;
                if (node is not null)
                {
                    node["version"] = sourceVersion;
                    if (!string.IsNullOrWhiteSpace(sourceCommit)) node["sourceCommit"] = sourceCommit;
                    var temporary = receiptPath + ".new-" + Guid.NewGuid().ToString("N");
                    File.WriteAllText(temporary, node.ToJsonString(JsonOptions), new UTF8Encoding(false));
                    File.Move(temporary, receiptPath, true);
                }
            }
            using var uninstall = Registry.CurrentUser.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Uninstall\AgentCity", writable: true);
            var location = uninstall?.GetValue("InstallLocation") as string;
            if (uninstall is not null && location is not null &&
                string.Equals(Path.GetFullPath(location).TrimEnd(Path.DirectorySeparatorChar), installRoot.TrimEnd(Path.DirectorySeparatorChar), StringComparison.OrdinalIgnoreCase))
                uninstall.SetValue("DisplayVersion", sourceVersion, RegistryValueKind.String);
        }
        catch { }
    }

    private static bool WaitForOwnerExit(UpdateInstallJob job, TimeSpan timeout)
    {
        if (!int.TryParse(job.OwnerPid, out var pid) || job.OwnerStartUtcTicks is null) return true;
        var deadline = DateTime.UtcNow + timeout;
        while (DateTime.UtcNow < deadline)
        {
            try
            {
                using var process = Process.GetProcessById(pid);
                if (process.HasExited) return true;
                // PID reuse must never be treated as the original app.
                if (process.StartTime.ToUniversalTime().Ticks != job.OwnerStartUtcTicks.Value) return true;
            }
            catch (ArgumentException) { return true; }
            catch (InvalidOperationException) { return true; }
            catch { return false; }
            Thread.Sleep(100);
        }
        return false;
    }

    public static bool VerifyDetachedManifest(byte[] manifestBytes, byte[] signatureBytes, string publicKeyPem)
    {
        try
        {
            var signed = Convert.FromBase64String(Encoding.UTF8.GetString(signatureBytes).Trim());
            using var rsa = RSA.Create();
            rsa.ImportFromPem(publicKeyPem);
            return rsa.KeySize >= 2048 && rsa.VerifyData(manifestBytes, signed, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
        }
        catch { return false; }
    }

    private static bool VerifyStagedPackage(UpdateInstallJob job, string staging, string publicKeyPem, bool allowLocalFiles = false)
    {
        try
        {
            if (job.PackagePath is null || job.ManifestPath is null || job.SignaturePath is null) return false;
            var package = ValidateFileTarget(job.PackagePath, job.UpdaterRoot);
            var manifestPath = ValidateFileTarget(job.ManifestPath, job.UpdaterRoot);
            var signaturePath = ValidateFileTarget(job.SignaturePath, job.UpdaterRoot);
            var manifestBytes = File.ReadAllBytes(manifestPath);
            if (!string.Equals(HashBytes(manifestBytes), job.ManifestSha256, StringComparison.OrdinalIgnoreCase)) return false;
            if (!VerifyDetachedManifest(manifestBytes, File.ReadAllBytes(signaturePath), publicKeyPem)) return false;
            var manifest = JsonSerializer.Deserialize<UpdateManifest>(manifestBytes, JsonOptions);
            if (manifest is null || manifest.SchemaVersion != 1 || !string.Equals(manifest.Version, job.Version, StringComparison.Ordinal) || !string.Equals(manifest.PackageSha256, job.PackageSha256, StringComparison.OrdinalIgnoreCase) ||
                manifest.PackageBytes != new FileInfo(package).Length || !string.Equals(HashFile(package), manifest.PackageSha256, StringComparison.OrdinalIgnoreCase) || !BuildVersionMatches(staging, job.Version)) return false;
            using var archive = ZipFile.OpenRead(package);
            var expected = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (var entry in archive.Entries)
            {
                if (entry.FullName.EndsWith('/') || string.IsNullOrEmpty(entry.Name)) continue;
                var relative = entry.FullName.Replace('/', Path.DirectorySeparatorChar);
                EnsureRelativePath(relative);
                if (!expected.Add(relative)) return false;
                var destination = Path.Combine(staging, relative);
                if (!File.Exists(destination) || new FileInfo(destination).Length != entry.Length || !string.Equals(HashFile(destination), HashArchiveEntry(entry), StringComparison.OrdinalIgnoreCase)) return false;
            }
            var actual = EnumerateFilesNoReparse(staging).Select(x => Path.GetRelativePath(staging, x))
                .Where(x => !allowLocalFiles || !ProtectedNames.Contains(x, StringComparer.OrdinalIgnoreCase)).ToHashSet(StringComparer.OrdinalIgnoreCase);
            return expected.SetEquals(actual);
        }
        catch { return false; }
    }

    private sealed class ReadLease : IDisposable
    {
        private readonly List<FileStream> streams = [];
        public ReadLease(string root, string[] additional, bool publicFilesOnly = false)
        {
            try
            {
                var files = EnumerateFilesNoReparse(root).Where(x => !publicFilesOnly ||
                    !ProtectedNames.Contains(Path.GetRelativePath(root, x), StringComparer.OrdinalIgnoreCase));
                foreach (var file in files.Concat(additional).Distinct(StringComparer.OrdinalIgnoreCase))
                    streams.Add(File.Open(file, FileMode.Open, FileAccess.Read, FileShare.Read));
            }
            catch { Dispose(); throw; }
        }
        public void Dispose() { foreach (var stream in streams) stream.Dispose(); streams.Clear(); }
    }

    private static string HashBytes(byte[] bytes) => Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();

    private static bool BuildVersionMatches(string staging, string expected)
    {
        try
        {
            using var document = JsonDocument.Parse(File.ReadAllText(Path.Combine(staging, "build-manifest.json"), Encoding.UTF8));
            return document.RootElement.TryGetProperty("applicationSourceVersion", out var version) &&
                string.Equals(version.GetString(), expected, StringComparison.Ordinal);
        }
        catch { return false; }
    }

    private static string HashArchiveEntry(ZipArchiveEntry entry)
    {
        using var stream = entry.Open();
        return Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
    }

    private static bool CheckSelfTest(string executable, string workingDirectory)
    {
        try
        {
            var start = new ProcessStartInfo(executable)
            {
                WorkingDirectory = workingDirectory,
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true
            };
            start.ArgumentList.Add("--self-test");
            using var process = Process.Start(start);
            if (process is null) return false;
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(30));
            process.WaitForExitAsync(timeout.Token).GetAwaiter().GetResult();
            return process.ExitCode == 0;
        }
        catch (OperationCanceledException) { return false; }
        catch { return false; }
    }

    private static void CopyProtectedFiles(string oldRoot, string newRoot)
    {
        foreach (var name in ProtectedNames)
        {
            var source = Path.Combine(oldRoot, name);
            if (!File.Exists(source)) continue;
            if ((File.GetAttributes(source) & FileAttributes.ReparsePoint) != 0) throw new InvalidDataException("Protected reparse file");
            EnsureRelativePath(name);
            var destination = Path.Combine(newRoot, name);
            if (File.Exists(destination)) throw new InvalidDataException("Protected package file");
            File.Copy(source, destination, false);
        }
    }

    private static bool IsHelperFile(string relative)
    {
        var name = Path.GetFileName(relative);
        if (relative.StartsWith("runtimes\\", StringComparison.OrdinalIgnoreCase)) return true;
        if (name.Equals("desktop-profile.json", StringComparison.OrdinalIgnoreCase) ||
            name.Equals("installation.json", StringComparison.OrdinalIgnoreCase) ||
            name.Equals("updates-channel.json", StringComparison.OrdinalIgnoreCase)) return false;
        return name.Equals("AgentCity.exe", StringComparison.OrdinalIgnoreCase) ||
            name.Equals("AgentCity.dll", StringComparison.OrdinalIgnoreCase) ||
            name.Equals("AgentCity.deps.json", StringComparison.OrdinalIgnoreCase) ||
            name.Equals("AgentCity.runtimeconfig.json", StringComparison.OrdinalIgnoreCase) ||
            name.StartsWith("Microsoft.Web.WebView2.", StringComparison.OrdinalIgnoreCase) &&
            (name.EndsWith(".dll", StringComparison.OrdinalIgnoreCase) || name.EndsWith(".json", StringComparison.OrdinalIgnoreCase));
    }

    internal static string ValidateRoot(string path, bool mustExist)
    {
        if (string.IsNullOrWhiteSpace(path)) throw new InvalidDataException("Invalid update root");
        var full = Path.GetFullPath(path);
        if (!Path.IsPathFullyQualified(full) || full.StartsWith("\\\\", StringComparison.Ordinal)) throw new InvalidDataException("Invalid update root");
        var root = Path.GetPathRoot(full)!;
        var current = root.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        foreach (var part in full[root.Length..].Split([Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar], StringSplitOptions.RemoveEmptyEntries))
        {
            current = Path.Combine(current + Path.DirectorySeparatorChar, part);
            if (Directory.Exists(current) || File.Exists(current))
            {
                var attr = File.GetAttributes(current);
                if ((attr & FileAttributes.ReparsePoint) != 0) throw new InvalidDataException("Reparse update root");
            }
        }
        if (mustExist && !Directory.Exists(full)) throw new DirectoryNotFoundException();
        return full.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
    }

    internal static string ValidateFileTarget(string path, string? expectedParent)
    {
        if (string.IsNullOrWhiteSpace(path) || !Path.IsPathFullyQualified(path)) throw new InvalidDataException("Invalid update file");
        var full = Path.GetFullPath(path);
        var parent = ValidateRoot(Path.GetDirectoryName(full)!, true);
        if (expectedParent != null && !string.Equals(parent, ValidateRoot(expectedParent, true), StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("Invalid update file");
        if (File.Exists(full) && (File.GetAttributes(full) & FileAttributes.ReparsePoint) != 0) throw new InvalidDataException("Reparse update file");
        return full;
    }

    internal static void EnsureOutside(string child, string parent)
    {
        if (SameOrInside(child, parent)) throw new InvalidDataException("Update roots overlap");
    }

    internal static void EnsureDisjoint(string first, string second)
    {
        if (SameOrInside(first, second) || SameOrInside(second, first)) throw new InvalidDataException("Update roots overlap");
    }

    internal static void EnsureInside(string child, string parent)
    {
        if (string.Equals(child, parent, StringComparison.OrdinalIgnoreCase) || !SameOrInside(child, parent)) throw new InvalidDataException("Update root outside workspace");
    }

    private static bool SameOrInside(string value, string root)
    {
        var v = value.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        var r = root.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        return v.StartsWith(r, StringComparison.OrdinalIgnoreCase) || string.Equals(value, root, StringComparison.OrdinalIgnoreCase);
    }

    internal static void EnsureRelativePath(string relative)
    {
        if (string.IsNullOrWhiteSpace(relative) || Path.IsPathRooted(relative) || relative.Contains(':') || relative.Contains('\0')) throw new InvalidDataException("Invalid update path");
        var normalized = relative.Replace('\\', '/');
        foreach (var part in normalized.Split('/'))
        {
            if (part.Length == 0 || part == "." || part == ".." || part.EndsWith('.') || part.EndsWith(' ')) throw new InvalidDataException("Invalid update path");
            var stem = part.Split('.')[0];
            if (stem.Equals("CON", StringComparison.OrdinalIgnoreCase) || stem.Equals("PRN", StringComparison.OrdinalIgnoreCase) ||
                stem.Equals("AUX", StringComparison.OrdinalIgnoreCase) || stem.Equals("NUL", StringComparison.OrdinalIgnoreCase) ||
                System.Text.RegularExpressions.Regex.IsMatch(stem, "^(COM|LPT)[1-9]$", System.Text.RegularExpressions.RegexOptions.IgnoreCase))
                throw new InvalidDataException("Invalid update path");
        }
    }

    internal static IEnumerable<string> EnumerateFilesNoReparse(string root)
    {
        var pending = new Stack<string>(); pending.Push(root);
        while (pending.Count > 0)
        {
            var directory = pending.Pop();
            foreach (var path in Directory.EnumerateFileSystemEntries(directory))
            {
                var attributes = File.GetAttributes(path);
                if ((attributes & FileAttributes.ReparsePoint) != 0) throw new InvalidDataException("Reparse update entry");
                if ((attributes & FileAttributes.Directory) != 0) pending.Push(path);
                else if ((attributes & FileAttributes.Normal) != 0 || File.Exists(path)) yield return path;
                else throw new InvalidDataException("Invalid update entry");
            }
        }
    }

    internal static string HashFile(string path)
    {
        using var stream = File.OpenRead(path);
        return Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
    }

    internal static void RequireSha256(string value)
    {
        if (!RegexHex(value, 64)) throw new InvalidDataException("Invalid update hash");
    }

    private static bool RegexHex(string value, int length) => value.Length == length && value.All(c => c is >= '0' and <= '9' or >= 'a' and <= 'f' or >= 'A' and <= 'F');

    internal static bool IsNewerVersion(string candidate, string current)
    {
        if (!SemVer.TryParse(candidate, out var next) || !SemVer.TryParse(current, out var old)) return false;
        return next.CompareTo(old) > 0;
    }

    private static void TryDeleteTree(string path)
    {
        try
        {
            if (!Directory.Exists(path)) return;
            foreach (var entry in EnumerateFilesNoReparse(path).ToArray()) File.Delete(entry);
            foreach (var dir in Directory.EnumerateDirectories(path, "*", SearchOption.AllDirectories).OrderByDescending(x => x.Length)) Directory.Delete(dir);
            Directory.Delete(path);
        }
        catch { }
    }

    private static void TryDeleteFile(string? jobPath)
    {
        if (jobPath is null) return;
        try { File.Delete(jobPath); } catch { }
    }

    internal readonly record struct SemVer(int Major, int Minor, int Patch, string[] Pre) : IComparable<SemVer>
    {
        public static bool TryParse(string? value, out SemVer result)
        {
            result = default;
            if (string.IsNullOrWhiteSpace(value)) return false;
            var match = System.Text.RegularExpressions.Regex.Match(value, "^(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z.-]+))?(?:\\+[0-9A-Za-z.-]+)?$");
            if (!match.Success || !int.TryParse(match.Groups[1].Value, out var major) || !int.TryParse(match.Groups[2].Value, out var minor) || !int.TryParse(match.Groups[3].Value, out var patch)) return false;
            var pre = match.Groups[4].Success ? match.Groups[4].Value.Split('.') : [];
            if (pre.Any(string.IsNullOrEmpty) || pre.Any(p => p.All(char.IsDigit) && p.Length > 1 && p[0] == '0')) return false;
            result = new SemVer(major, minor, patch, pre); return true;
        }
        public int CompareTo(SemVer other)
        {
            var c = Major.CompareTo(other.Major); if (c != 0) return c;
            c = Minor.CompareTo(other.Minor); if (c != 0) return c;
            c = Patch.CompareTo(other.Patch); if (c != 0) return c;
            if (Pre.Length == 0) return other.Pre.Length == 0 ? 0 : 1;
            if (other.Pre.Length == 0) return -1;
            for (var i = 0; i < Math.Max(Pre.Length, other.Pre.Length); i++)
            {
                if (i >= Pre.Length) return -1; if (i >= other.Pre.Length) return 1;
                var leftNumber = int.TryParse(Pre[i], out var left); var rightNumber = int.TryParse(other.Pre[i], out var right);
                if (leftNumber && rightNumber) { c = left.CompareTo(right); } else if (leftNumber != rightNumber) { c = leftNumber ? -1 : 1; } else c = StringComparer.Ordinal.Compare(Pre[i], other.Pre[i]);
                if (c != 0) return c;
            }
            return 0;
        }
    }
}
