using System.IO.Compression;
using System.Net;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace AgentCityDesktop;

public sealed record UpdateChannel(string Kind, string? Path, string? Repository)
{
    public static UpdateChannel? LoadAdjacent(string stableConfigFile)
    {
        var config = UpdateInstall.ValidateFileTarget(stableConfigFile, System.IO.Path.GetDirectoryName(stableConfigFile));
        var path = System.IO.Path.Combine(System.IO.Path.GetDirectoryName(config)!, "updates-channel.json");
        if (!File.Exists(path)) return null;
        if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0) throw new InvalidDataException("Invalid update channel");
        var value = JsonSerializer.Deserialize<UpdateChannel>(File.ReadAllText(path, Encoding.UTF8), UpdateInstall.JsonOptions)
            ?? throw new InvalidDataException("Invalid update channel");
        if (value.Kind is not ("local" or "github")) throw new InvalidDataException("Invalid update channel");
        if (value.Kind == "local" && string.IsNullOrWhiteSpace(value.Path)) throw new InvalidDataException("Invalid update channel");
        if (value.Kind == "github" && !IsRepository(value.Repository)) throw new InvalidDataException("Invalid update channel");
        return value;
    }

    internal static bool IsRepository(string? value) => value is not null &&
        System.Text.RegularExpressions.Regex.IsMatch(value, "^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$");
}

public sealed record UpdateCheckResult(bool Available, string? Version, string? PendingJobPath, string? Reason)
{
    public static UpdateCheckResult None(string reason) => new(false, null, null, reason);
}

public sealed record AppUpdaterOptions(
    string StableConfigFile,
    string InstallRoot,
    string UpdaterRoot,
    string CurrentVersion,
    string PublicKeyPem,
    TimeSpan? Interval = null);

public sealed class AppUpdater : IDisposable
{
    public const long MaxPackageBytes = 512L * 1024 * 1024;
    private const long MaxUncompressedBytes = 768L * 1024 * 1024;
    private const int MaxEntries = 4096;
    private const int MaxManifestBytes = 1024 * 1024;
    private readonly AppUpdaterOptions options;
    private readonly HttpClient http;
    private readonly SemaphoreSlim checkGate = new(1, 1);
    private CancellationTokenSource? periodicStop;
    private Task? periodicTask;
    private string? stagedVersion;
    private string? stagedJobPath;

    public AppUpdater(AppUpdaterOptions options, HttpClient? httpClient = null)
    {
        this.options = options;
        if (string.IsNullOrWhiteSpace(options.PublicKeyPem)) throw new ArgumentException("Pinned update key required", nameof(options));
        http = httpClient ?? new HttpClient();
        http.DefaultRequestHeaders.UserAgent.Clear();
        http.DefaultRequestHeaders.UserAgent.Add(new ProductInfoHeaderValue("AgentCity", "1"));
    }

    public void StartPeriodic(Func<UpdateCheckResult, Task>? onResult = null)
    {
        if (periodicTask is not null) return;
        var stop = new CancellationTokenSource();
        periodicStop = stop;
        periodicTask = Task.Run(async () =>
        {
            var interval = options.Interval.GetValueOrDefault(TimeSpan.FromHours(6));
            if (interval < TimeSpan.FromMinutes(1)) interval = TimeSpan.FromHours(6);
            while (!stop.IsCancellationRequested)
            {
                UpdateCheckResult result;
                try { result = await CheckAndStageAsync(periodicStop.Token).ConfigureAwait(false); }
                catch (OperationCanceledException) when (stop.IsCancellationRequested) { break; }
                catch { result = UpdateCheckResult.None("check-failed"); }
                if (onResult is not null) try { await onResult(result).ConfigureAwait(false); } catch { }
                try { await Task.Delay(interval, stop.Token).ConfigureAwait(false); }
                catch (OperationCanceledException) when (stop.IsCancellationRequested) { break; }
            }
        }, stop.Token);
    }

    public async Task<UpdateCheckResult> CheckAndStageAsync(CancellationToken cancellationToken = default)
    {
        await checkGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try { return await CheckAndStageCoreAsync(cancellationToken).ConfigureAwait(false); }
        finally { checkGate.Release(); }
    }

    private async Task<UpdateCheckResult> CheckAndStageCoreAsync(CancellationToken cancellationToken)
    {
        var channel = UpdateChannel.LoadAdjacent(options.StableConfigFile);
        if (channel is null) return UpdateCheckResult.None("channel-not-configured");
        var candidate = channel.Kind == "local"
            ? await ReadLocalAsync(channel, cancellationToken).ConfigureAwait(false)
            : await ReadGitHubAsync(channel, cancellationToken).ConfigureAwait(false);
        if (candidate is null) return UpdateCheckResult.None("no-release");
        if (!UpdateInstall.IsNewerVersion(candidate.Manifest.Version, options.CurrentVersion)) return UpdateCheckResult.None("not-newer");
        if (string.Equals(stagedVersion, candidate.Manifest.Version, StringComparison.Ordinal) && stagedJobPath is not null && File.Exists(stagedJobPath))
            return new UpdateCheckResult(true, stagedVersion, stagedJobPath, null);
        var stage = await StageAsync(candidate, cancellationToken).ConfigureAwait(false);
        stagedVersion = candidate.Manifest.Version; stagedJobPath = stage;
        return new UpdateCheckResult(true, candidate.Manifest.Version, stage, null);
    }

    public void Dispose()
    {
        var stop = Interlocked.Exchange(ref periodicStop, null);
        stop?.Cancel();
        // Do not block the UI thread while a callback is returning to the window.
        var task = Interlocked.Exchange(ref periodicTask, null);
        if (task is not null) _ = task.ContinueWith(_ => stop?.Dispose(), CancellationToken.None, TaskContinuationOptions.ExecuteSynchronously, TaskScheduler.Default);
        http.Dispose();
    }

    private async Task<PendingRelease?> ReadLocalAsync(UpdateChannel channel, CancellationToken ct)
    {
        var directory = Path.IsPathFullyQualified(channel.Path!)
            ? Path.GetFullPath(channel.Path!)
            : Path.GetFullPath(Path.Combine(Path.GetDirectoryName(options.StableConfigFile)!, channel.Path!));
        directory = UpdateInstall.ValidateRoot(directory, true);
        var latest = Path.Combine(directory, "latest.json");
        var signature = latest + ".sig";
        var manifestBytes = ReadBounded(latest, MaxManifestBytes);
        var signatureBytes = ReadBounded(signature, 8192);
        var manifest = ParseManifest(manifestBytes);
        VerifyManifest(manifestBytes, signatureBytes);
        var package = Path.Combine(directory, manifest.PackageName);
        if (!IsSafePackageName(manifest.PackageName) || !File.Exists(package)) throw new InvalidDataException("Invalid update package");
        return new PendingRelease(manifest, manifestBytes, signatureBytes, package, manifest.PackageName);
    }

    private async Task<PendingRelease?> ReadGitHubAsync(UpdateChannel channel, CancellationToken ct)
    {
        var repository = channel.Repository!;
        var metadataUri = new Uri("https://api.github.com/repos/" + repository + "/releases/latest");
        using var metadataResponse = await http.GetAsync(metadataUri, HttpCompletionOption.ResponseHeadersRead, ct).ConfigureAwait(false);
        if (metadataResponse.StatusCode is HttpStatusCode.NotFound or HttpStatusCode.Forbidden) return null;
        metadataResponse.EnsureSuccessStatusCode();
        using var metadata = JsonDocument.Parse(await metadataResponse.Content.ReadAsByteArrayAsync(ct).ConfigureAwait(false));
        var root = metadata.RootElement;
        if (root.GetProperty("draft").GetBoolean() || root.GetProperty("prerelease").GetBoolean()) return null;
        var assets = root.GetProperty("assets").EnumerateArray().ToArray();
        var latestAsset = FindAsset(assets, "latest.json");
        var signatureAsset = FindAsset(assets, "latest.json.sig");
        if (latestAsset is null || signatureAsset is null) return null;
        var tag = root.GetProperty("tag_name").GetString() ?? throw new InvalidDataException("Invalid release");
        var latestBytes = await DownloadAssetAsync(repository, tag, latestAsset.Value, MaxManifestBytes, ct).ConfigureAwait(false);
        var signatureBytes = await DownloadAssetAsync(repository, tag, signatureAsset.Value, 8192, ct).ConfigureAwait(false);
        if (latestBytes.Length > MaxManifestBytes || signatureBytes.Length > 8192) throw new InvalidDataException("Invalid update manifest");
        var manifest = ParseManifest(latestBytes);
        VerifyManifest(latestBytes, signatureBytes);
        if (!UpdateInstall.IsNewerVersion(manifest.Version, options.CurrentVersion) ||
            (string.Equals(stagedVersion, manifest.Version, StringComparison.Ordinal) && stagedJobPath is not null && File.Exists(stagedJobPath)))
            return new PendingRelease(manifest, latestBytes, signatureBytes, string.Empty, manifest.PackageName);
        var packageAsset = FindAsset(assets, manifest.PackageName);
        if (packageAsset is null || !IsSafePackageName(manifest.PackageName)) return null;
        var packagePath = Path.Combine(UpdateInstall.ValidateRoot(options.UpdaterRoot, true), "download-" + Guid.NewGuid().ToString("N") + ".zip");
        var packageBytes = await DownloadAssetAsync(repository, tag, packageAsset.Value, MaxPackageBytes, ct).ConfigureAwait(false);
        if (packageBytes.LongLength != manifest.PackageBytes || packageBytes.LongLength > MaxPackageBytes) throw new InvalidDataException("Invalid update package size");
        File.WriteAllBytes(packagePath, packageBytes);
        return new PendingRelease(manifest, latestBytes, signatureBytes, packagePath, manifest.PackageName);
    }

    private async Task<string> StageAsync(PendingRelease release, CancellationToken ct)
    {
        var updater = UpdateInstall.ValidateRoot(options.UpdaterRoot, true);
        var package = UpdateInstall.ValidateFileTarget(release.PackagePath, Path.GetDirectoryName(release.PackagePath));
        var info = new FileInfo(package);
        if (info.Length != release.Manifest.PackageBytes || info.Length > MaxPackageBytes) throw new InvalidDataException("Invalid update package size");
        if (!string.Equals(UpdateInstall.HashFile(package), release.Manifest.PackageSha256, StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("Invalid update package hash");
        var stage = Path.Combine(updater, "staging-" + Guid.NewGuid().ToString("N"));
        var retainedPackage = Path.Combine(updater, "package-" + Guid.NewGuid().ToString("N") + ".zip");
        var retainedManifest = Path.Combine(updater, "manifest-" + Guid.NewGuid().ToString("N") + ".json");
        var retainedSignature = Path.Combine(updater, "manifest-" + Guid.NewGuid().ToString("N") + ".sig");
        var helperPlaceholder = Path.Combine(updater, "helper-pending-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(stage);
        Directory.CreateDirectory(helperPlaceholder);
        try
        {
            File.Copy(package, retainedPackage, false);
            File.WriteAllBytes(retainedManifest, release.ManifestBytes);
            File.WriteAllBytes(retainedSignature, release.SignatureBytes);
            ExtractAndVerify(retainedPackage, stage, release.Manifest);
            var manifestSha = Convert.ToHexString(SHA256.HashData(release.ManifestBytes)).ToLowerInvariant();
            var jobPath = Path.Combine(updater, "pending-" + Guid.NewGuid().ToString("N") + ".json");
            var job = new UpdateInstallJob(UpdateInstallJob.CurrentSchemaVersion, release.Manifest.Version,
                UpdateInstall.ValidateRoot(options.InstallRoot, true), stage, updater,
                helperPlaceholder, release.Manifest.PackageSha256, manifestSha, retainedPackage, retainedManifest, retainedSignature);
            Directory.CreateDirectory(job.HelperRoot);
            job.Save(jobPath);
            return jobPath;
        }
        catch
        {
            DeletePath(stage); DeletePath(retainedPackage); DeletePath(retainedManifest); DeletePath(retainedSignature); DeletePath(helperPlaceholder);
            throw;
        }
        finally
        {
            try { if (release.PackagePath.StartsWith(Path.Combine(updater, "download-"), StringComparison.OrdinalIgnoreCase)) File.Delete(release.PackagePath); } catch { }
        }
    }

    private void ExtractAndVerify(string package, string stage, UpdateManifest manifest)
    {
        using var archive = ZipFile.OpenRead(package);
        if (archive.Entries.Count == 0 || archive.Entries.Count > MaxEntries) throw new InvalidDataException("Invalid update archive");
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        long expanded = 0;
        foreach (var entry in archive.Entries)
        {
            var relative = entry.FullName.Replace('/', Path.DirectorySeparatorChar).Replace('\\', Path.DirectorySeparatorChar);
            if (relative.EndsWith(Path.DirectorySeparatorChar) || entry.Length == 0 && string.IsNullOrEmpty(entry.Name)) continue;
            UpdateInstall.EnsureRelativePath(relative);
            if (!seen.Add(relative) || ProtectedPackageFile(relative)) throw new InvalidDataException("Invalid update archive path");
            if (entry.Length > MaxPackageBytes || (expanded += entry.Length) > MaxUncompressedBytes) throw new InvalidDataException("Invalid update archive size");
            var destination = Path.Combine(stage, relative);
            Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
            using var source = entry.Open(); using var target = new FileStream(destination, FileMode.CreateNew, FileAccess.Write, FileShare.None);
            source.CopyTo(target);
        }
        var buildManifest = Path.Combine(stage, "build-manifest.json");
        if (!File.Exists(buildManifest)) throw new InvalidDataException("Build inventory missing");
        var inventory = ParseInventory(ReadBounded(buildManifest, MaxManifestBytes));
        var actualFiles = UpdateInstall.EnumerateFilesNoReparse(stage).Select(x => Path.GetRelativePath(stage, x).Replace('\\', '/')).ToHashSet(StringComparer.OrdinalIgnoreCase);
        var expectedFiles = inventory.Keys.Append("build-manifest.json").ToHashSet(StringComparer.OrdinalIgnoreCase);
        if (!actualFiles.SetEquals(expectedFiles)) throw new InvalidDataException("Build inventory mismatch");
        foreach (var item in inventory)
        {
            var path = Path.Combine(stage, item.Key);
            if (new FileInfo(path).Length != item.Value.Bytes || !string.Equals(UpdateInstall.HashFile(path), item.Value.Sha256, StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("Build inventory hash mismatch");
        }
        if (!actualFiles.Contains("AgentCity.exe")) throw new InvalidDataException("Update host missing");
    }

    private void VerifyManifest(byte[] bytes, byte[] signature)
    {
        if (!UpdateInstall.VerifyDetachedManifest(bytes, signature, options.PublicKeyPem)) throw new InvalidDataException("Invalid update signature");
    }

    private static UpdateManifest ParseManifest(byte[] bytes)
    {
        var value = JsonSerializer.Deserialize<UpdateManifest>(bytes, UpdateInstall.JsonOptions) ?? throw new InvalidDataException("Invalid update manifest");
        if (value.SchemaVersion != 1 || !UpdateInstall.IsNewerVersion(value.Version, "0.0.0") || !IsSafePackageName(value.PackageName)) throw new InvalidDataException("Invalid update manifest");
        UpdateInstall.RequireSha256(value.PackageSha256);
        if (value.PackageBytes is <= 0 or > MaxPackageBytes) throw new InvalidDataException("Invalid update manifest");
        return value;
    }

    private static Dictionary<string, InventoryItem> ParseInventory(byte[] bytes)
    {
        using var document = JsonDocument.Parse(bytes);
        var root = document.RootElement;
        if (!root.TryGetProperty("files", out var files) || files.ValueKind != JsonValueKind.Array) throw new InvalidDataException("Invalid build inventory");
        var result = new Dictionary<string, InventoryItem>(StringComparer.OrdinalIgnoreCase);
        foreach (var file in files.EnumerateArray())
        {
            var path = file.GetProperty("path").GetString() ?? throw new InvalidDataException("Invalid build inventory");
            path = path.Replace('\\', '/');
            UpdateInstall.EnsureRelativePath(path);
            var sha = file.GetProperty("sha256").GetString() ?? ""; UpdateInstall.RequireSha256(sha);
            var bytesCount = file.GetProperty("bytes").GetInt64(); if (bytesCount < 0 || bytesCount > AppUpdater.MaxUncompressedBytes) throw new InvalidDataException("Invalid build inventory");
            if (!result.TryAdd(path, new InventoryItem(sha, bytesCount))) throw new InvalidDataException("Duplicate build inventory path");
        }
        return result;
    }

    private async Task<byte[]> DownloadAssetAsync(string repository, string tag, JsonElement asset, long maxBytes, CancellationToken ct)
    {
        var name = asset.GetProperty("name").GetString() ?? throw new InvalidDataException("Invalid release asset");
        var url = asset.GetProperty("browser_download_url").GetString() ?? throw new InvalidDataException("Invalid release asset");
        if (!IsSafePackageName(name) && name is not ("latest.json" or "latest.json.sig")) throw new InvalidDataException("Invalid release asset");
        var expected = new Uri($"https://github.com/{repository}/releases/download/{Uri.EscapeDataString(tag)}/{Uri.EscapeDataString(name)}");
        if (!Uri.TryCreate(url, UriKind.Absolute, out var actual) || actual.Scheme != Uri.UriSchemeHttps || actual.Host != "github.com" || actual.Query != "" || actual.AbsolutePath != expected.AbsolutePath) throw new InvalidDataException("Invalid release asset");
        using var response = await http.GetAsync(actual, HttpCompletionOption.ResponseHeadersRead, ct).ConfigureAwait(false);
        response.EnsureSuccessStatusCode();
        if (response.Content.Headers.ContentLength is long contentLength && contentLength > maxBytes) throw new InvalidDataException("Invalid release asset size");
        await using var source = await response.Content.ReadAsStreamAsync(ct).ConfigureAwait(false);
        using var target = new MemoryStream();
        var buffer = new byte[64 * 1024];
        while (true)
        {
            var read = await source.ReadAsync(buffer.AsMemory(), ct).ConfigureAwait(false);
            if (read == 0) break;
            if (target.Length + read > maxBytes) throw new InvalidDataException("Invalid release asset size");
            await target.WriteAsync(buffer.AsMemory(0, read), ct).ConfigureAwait(false);
        }
        return target.ToArray();
    }

    private static JsonElement? FindAsset(JsonElement[] assets, string name)
    {
        foreach (var asset in assets) if (asset.TryGetProperty("name", out var value) && value.GetString() == name) return asset;
        return null;
    }
    private static byte[] ReadBounded(string path, int max) { var info = new FileInfo(path); if (!info.Exists || info.Length > max) throw new InvalidDataException("Invalid update file"); return File.ReadAllBytes(path); }
    private static bool IsSafePackageName(string name) => name.EndsWith(".zip", StringComparison.OrdinalIgnoreCase) && name.Length <= 200 && name.IndexOfAny(['/', '\\', ':']) < 0;
    private static bool ProtectedPackageFile(string path)
    {
        var name = Path.GetFileName(path);
        return name.Equals("desktop-profile.json", StringComparison.OrdinalIgnoreCase) ||
            name.Equals("installation.json", StringComparison.OrdinalIgnoreCase) ||
            name.Equals("Uninstall-AgentCity.ps1", StringComparison.OrdinalIgnoreCase) ||
            name.Equals("updates-channel.json", StringComparison.OrdinalIgnoreCase);
    }
    private static void DeletePath(string path)
    {
        try
        {
            if (Directory.Exists(path)) Directory.Delete(path, true);
            else if (File.Exists(path)) File.Delete(path);
        }
        catch { }
    }
    private sealed record PendingRelease(UpdateManifest Manifest, byte[] ManifestBytes, byte[] SignatureBytes, string PackagePath, string PackageName);
    private sealed record InventoryItem(string Sha256, long Bytes);
}

public sealed record UpdateManifest(int SchemaVersion, string Version, string PackageName, string PackageSha256, long PackageBytes);
