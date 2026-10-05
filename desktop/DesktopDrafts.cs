using System.Text.Json;
using System.Linq;

namespace AgentCityDesktop;

internal sealed record DraftFlags(bool Dirty, bool Busy);
internal static class DesktopDrafts
{
    public const string Snapshot = "(()=>window.agentCityDrafts?.snapshot()??null)()";
    public static DraftFlags? Parse(string response)
    {
        if (response.Length > 128) return null;
        try
        {
            using var json = JsonDocument.Parse(response); var root = json.RootElement;
            if (root.ValueKind != JsonValueKind.Object) return null;
            var names = root.EnumerateObject().Select(p => p.Name).ToArray();
            if (names.Length != 3 || names.Distinct().Count() != 3 ||
                !root.TryGetProperty("version", out var version) || !version.TryGetInt32(out var v) || v != 1 ||
                !root.TryGetProperty("dirty", out var dirty) || dirty.ValueKind is not (JsonValueKind.True or JsonValueKind.False) ||
                !root.TryGetProperty("busy", out var busy) || busy.ValueKind is not (JsonValueKind.True or JsonValueKind.False)) return null;
            return new(dirty.GetBoolean(), busy.GetBoolean());
        }
        catch { return null; }
    }
    public static string Request(string id, string action, bool allowPrompt) => $"window.agentCityDrafts?.request({JsonSerializer.Serialize(id)},{JsonSerializer.Serialize(action)},{(allowPrompt ? "true" : "false")})??'cancel'";
    public static string Poll(string id) => $"window.agentCityDrafts?.poll({JsonSerializer.Serialize(id)})??'cancel'";
    public static string Cancel(string id) => $"window.agentCityDrafts?.cancel({JsonSerializer.Serialize(id)})";
}
