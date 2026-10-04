using System.Text.Json;

namespace AgentCityDesktop;

internal static class RecoveryScripts
{
    private static readonly string template = ReadTemplate();
    private static string ReadTemplate()
    {
        using var stream = typeof(RecoveryScripts).Assembly.GetManifestResourceStream("AgentCity.Desktop.Recovery.js")
            ?? throw new InvalidDataException("Recovery resource missing");
        using var reader = new StreamReader(stream);
        return reader.ReadToEnd();
    }
    public static string Start(string operation, string capability) => "(" + template + ")(" + JsonSerializer.Serialize(operation) + "," + JsonSerializer.Serialize(capability) + ")";
    public static string Poll(string operation) => "(()=>{const s=window.__agentCityDesktopRecovery;return s&&s.operation===" +
        JsonSerializer.Serialize(operation) + "&&s.document===performance.timeOrigin?s.status:'missing';})()";
    public static string Clear(string operation) => "(()=>{const s=window.__agentCityDesktopRecovery;if(s&&s.operation===" +
        JsonSerializer.Serialize(operation) + "){s.controller.abort();delete window.__agentCityDesktopRecovery;}return 'cleared';})()";
    public static string Primitive(string encoded)
    {
        using var doc = JsonDocument.Parse(encoded);
        if (doc.RootElement.ValueKind != JsonValueKind.String) throw new InvalidDataException("Primitive recovery result required");
        var value = doc.RootElement.GetString();
        if (value is not ("started" or "pending" or "ok" or "refused" or "expired" or "missing" or "cleared"))
            throw new InvalidDataException("Unexpected recovery result");
        return value;
    }
}

internal sealed class BackendHealth
{
    public bool Unavailable { get; private set; }
    public void Observe(JsonElement result, bool localOnly)
    {
        if (result.GetProperty("localOnly").GetBoolean() != localOnly) throw new InvalidDataException("Runtime mismatch");
        Unavailable = !result.GetProperty("backendAlive").GetBoolean();
    }
    public void LostControl() => Unavailable = true;
}
