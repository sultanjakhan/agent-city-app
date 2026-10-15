using System.Drawing;
using System.Text.Json;
using AgentCityDesktop;

internal static class WindowPlacementContract
{
    private static void Check(bool condition, string reason)
    {
        if (!condition) throw new Exception(reason);
    }

    public static int Main()
    {
        var primary = new Rectangle(0, 0, 1920, 1040);
        var secondary = new Rectangle(-1600, 0, 1600, 860);
        var original = new WindowPlacement(-1450, 80, 1220, 700, false);
        Check(original.Fit([primary, secondary]) == original, "Position on a negative-coordinate display changed");
        var disconnected = original.Fit([primary]);
        Check(primary.Contains(disconnected.Bounds), "Removed display left window off-screen");
        Check(disconnected.Width == original.Width && disconnected.Height == original.Height, "Monitor removal changed a fitting size");
        var oversized = new WindowPlacement(1500, 700, 3000, 2000, true).Fit([primary]);
        Check(oversized.Bounds == primary && oversized.Maximized, "Large window did not fit the available work area");
        var smallDisplay = new Rectangle(0, 0, 640, 480);
        Check(original.Fit([smallDisplay]).Bounds == smallDisplay, "Minimum dimensions hid window controls on a small display");
        var partial = new WindowPlacement(1800, 800, 900, 600, false).Fit([primary]);
        Check(primary.Contains(partial.Bounds) && partial.X == 1020 && partial.Y == 440, "Partially off-screen bounds were not clamped");
        Check(new WindowPlacement(0, 0, 100, 100, false).Fit([primary]).Bounds.Size == new Size(760, 520), "Minimum normal size was lost");
        Check(WindowPlacementStore.ForScope("../invalid") == null, "Invalid profile scope accepted");

        var directory = Path.Combine(Path.GetTempPath(), "agent-city-placement-contract-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        try
        {
            var path = Path.Combine(directory, "first.json");
            var first = new WindowPlacementStore(path);
            var second = new WindowPlacementStore(Path.Combine(directory, "second.json"));
            Check(first.Load() == null, "First launch did not retain default bounds");
            first.Save(original);
            Check(first.Load() == original && second.Load() == null, "Placement round-trip/profile isolation failed");
            first.Save(original with { Maximized = true });
            Check(first.Load()!.Maximized, "Maximized state was lost");
            Check(!Directory.GetFiles(directory, "*.tmp").Any(), "Atomic save leaked temporary files");
            foreach (var invalid in new[]
            {
                "", "malformed", "null", "{}", "{\"Version\":2}",
                JsonSerializer.Serialize(new { Version = 1, Placement = original with { Width = 0 } }),
                JsonSerializer.Serialize(new { Version = 1, Placement = original with { X = int.MaxValue } }),
                new string('x', 2049)
            })
            {
                File.WriteAllText(path, invalid);
                Check(first.Load() == null, "Invalid preference did not fall back to default bounds");
            }
            var obstacle = Path.Combine(directory, "file-instead-of-directory");
            File.WriteAllText(obstacle, "synthetic obstacle");
            var unavailable = new WindowPlacementStore(Path.Combine(obstacle, "placement.json"));
            unavailable.Save(original);
            Check(unavailable.Load() == null, "An unwritable preference interrupted default startup");
            Check(File.ReadAllText(obstacle) == "synthetic obstacle", "Preference save overwrote an existing file");
        }
        finally { Directory.Delete(directory, true); }
        Console.WriteLine("PASS window placement: round-trip, profile isolation, malformed/unwritable fallback, maximized state, monitor removal and clamping; no native windows opened");
        return 0;
    }
}
