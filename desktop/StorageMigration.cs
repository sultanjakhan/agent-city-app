using System.Diagnostics;

namespace AgentCityDesktop;

internal static class StorageMigration
{
    // Called after AgentPipe disposal and the owned backend's confirmed exit.
    // Current profile instance lock is retained until migration and close finish.
    public static async Task ApplyPrepared(string config)
    {
        if (!File.Exists(config + ".migration.json")) return;
        var info = new ProcessStartInfo(Path.Combine(AppContext.BaseDirectory, "backend", "AgentCityBackend.exe"))
        {
            WorkingDirectory = AppContext.BaseDirectory, UseShellExecute = false,
            CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true
        };
        info.ArgumentList.Add("--apply-storage-migration"); info.ArgumentList.Add(config);
        using var process = Process.Start(info) ?? throw new IOException("Storage migration unavailable");
        var output = process.StandardOutput.ReadToEndAsync();
        var errors = process.StandardError.ReadToEndAsync();
        await process.WaitForExitAsync();
        await Task.WhenAll(output, errors);
        // Failure remains in the private migration receipt, shown next launch.
        // No secret payload, source file body or child exception is logged.
    }
}
