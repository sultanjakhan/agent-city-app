using System.Drawing;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace AgentCityDesktop;

// Presentation state only. It is separate from the storage configuration and
// browser profile, and a missing/unwritable file never prevents app startup.
internal sealed record WindowPlacement(int X, int Y, int Width, int Height, bool Maximized)
{
    [JsonIgnore] public Rectangle Bounds => new(X, Y, Width, Height);
    [JsonIgnore] public bool Valid => X is >= -1000000 and <= 1000000 && Y is >= -1000000 and <= 1000000 &&
        Width is > 0 and <= 100000 && Height is > 0 and <= 100000;

    public WindowPlacement Fit(IReadOnlyList<Rectangle> workingAreas)
    {
        if (!Valid || workingAreas.Count == 0) throw new ArgumentException("Invalid window placement");
        var areas = workingAreas.Where(area => area.Width > 0 && area.Height > 0).ToArray();
        if (areas.Length == 0) throw new ArgumentException("No display working area");
        // Keep a window on its existing display where possible. The first area
        // is the primary display, used if its old monitor was disconnected.
        var area = areas.OrderByDescending(candidate =>
        {
            var overlap = Rectangle.Intersect(Bounds, candidate);
            return (long)Math.Max(0, overlap.Width) * Math.Max(0, overlap.Height);
        }).First();
        var width = Math.Clamp(Width, Math.Min(760, area.Width), area.Width);
        var height = Math.Clamp(Height, Math.Min(520, area.Height), area.Height);
        return this with
        {
            X = Math.Clamp(X, area.Left, area.Right - width),
            Y = Math.Clamp(Y, area.Top, area.Bottom - height),
            Width = width,
            Height = height
        };
    }
}

internal sealed class WindowPlacementStore(string path)
{
    private sealed record State(int Version, WindowPlacement Placement);

    public static WindowPlacementStore? ForScope(string? scope)
    {
        if (scope == null || scope.Length != 32 || scope.Any(c => !char.IsAsciiHexDigit(c))) return null;
        return new WindowPlacementStore(Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "Agent City", "window-state", scope + ".json"));
    }

    public WindowPlacement? Load()
    {
        try
        {
            if (!File.Exists(path) || new FileInfo(path).Length > 2048) return null;
            var state = JsonSerializer.Deserialize<State>(File.ReadAllText(path));
            return state is { Version: 1, Placement.Valid: true } ? state.Placement : null;
        }
        catch { return null; }
    }

    public void Save(WindowPlacement placement)
    {
        if (!placement.Valid) return;
        var temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            File.WriteAllText(temporary, JsonSerializer.Serialize(new State(1, placement)));
            File.Move(temporary, path, true);
        }
        catch { } // A presentation preference must never interrupt moving/closing.
        finally { try { File.Delete(temporary); } catch { } }
    }
}
