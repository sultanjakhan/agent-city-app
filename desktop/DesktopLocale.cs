using System;
using System.Text.Json;
using System.Threading.Tasks;

namespace AgentCityDesktop;

// Read-only host contract; does not enable WebMessage or host objects.
// The caller must check exact same-origin AND document epoch before/after await.
internal sealed class DesktopLocale
{
    public const string SnapshotScript = "(()=>typeof I18n==='undefined'?null:{version:1,language:I18n.language})()";
    private string? language;
    private long? acceptedEpoch;
    private long readSequence;

    public void Invalidate()
    {
        readSequence++;
        language = null;
        acceptedEpoch = null;
    }

    public string? LanguageFor(long epoch) => acceptedEpoch == epoch ? language : null;
    public string? CopyFor(string key, long epoch, Func<long, bool> isCurrentDocument)
    {
        if (!isCurrentDocument(epoch)) return null;
        var selected = LanguageFor(epoch);
        return selected == null ? null : DesktopText.ForLanguage(key, selected);
    }

    public async Task<bool> ReadAsync(Func<string, Task<string>> executeReadOnly,
        long epoch, Func<long, bool> isCurrentDocument)
    {
        if (!isCurrentDocument(epoch)) return false;
        var sequence = ++readSequence;
        string? selected;
        try { selected = Parse(await executeReadOnly(SnapshotScript).WaitAsync(TimeSpan.FromSeconds(2))); }
        catch { return false; } // No private response or exception logging.
        if (selected == null || sequence != readSequence || !isCurrentDocument(epoch)) return false;
        language = selected;
        acceptedEpoch = epoch;
        return true;
    }

    public static string? Parse(string? response)
    {
        if (response == null || response.Length > 64) return null;
        try
        {
            using var document = JsonDocument.Parse(response);
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object) return null;
            var count = 0;
            foreach (var property in root.EnumerateObject())
            {
                if (property.Name != "version" && property.Name != "language") return null;
                count++;
            }
            if (count != 2 || !root.TryGetProperty("version", out var version) ||
                version.ValueKind != JsonValueKind.Number || !version.TryGetInt32(out var number) || number != 1 ||
                !root.TryGetProperty("language", out var locale) || locale.ValueKind != JsonValueKind.String) return null;
            var selected = locale.GetString();
            return selected is "ru" or "en" ? selected : null;
        }
        catch (JsonException) { return null; }
    }
}
