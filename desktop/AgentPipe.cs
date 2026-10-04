using System.IO.Pipes;
using System.Security.Principal;
using System.Text;
using System.Text.Json;
using System.Security.Cryptography;

namespace AgentCityDesktop;

// Local, current OS account authority. No browser grants or credentials leave the host.
internal sealed class AgentPipe : IDisposable
{
    private const int RequestLimit = 16000, ReplyLimit = 1024 * 1024;
    private readonly string name;
    private readonly Func<JsonElement, Task<JsonElement>> dispatch;
    private readonly CancellationTokenSource stop = new();
    private Task? worker;
    private static readonly UTF8Encoding Utf8 = new(false, true);

    public AgentPipe(string name, Func<JsonElement, Task<JsonElement>> dispatch)
    { this.name = name; this.dispatch = dispatch; }
    public static string Name(string config)
    {
        var sid = WindowsIdentity.GetCurrent().User?.Value ?? throw new InvalidOperationException();
        var identity = sid + "\n" + Path.GetFullPath(config).ToUpperInvariant();
        return "AgentCityAgent-" + Convert.ToHexString(SHA256.HashData(Utf8.GetBytes(identity))).ToLowerInvariant()[..32];
    }
    private static void Exact(JsonElement value, params string[] fields)
    {
        if (value.ValueKind != JsonValueKind.Object) throw new InvalidDataException();
        var names = value.EnumerateObject().Select(p => p.Name).ToArray();
        if (names.Length != fields.Length || names.Distinct().Count() != names.Length || fields.Except(names).Any())
            throw new InvalidDataException();
    }
    public static JsonElement Validate(JsonElement value)
    {
        Exact(value, "method", "path", "body");
        var method = value.GetProperty("method").GetString();
        var path = value.GetProperty("path").GetString() ?? "";
        if (path.Length > 2048 || path.Any(c => c < 32) || !path.StartsWith('/') || path.StartsWith("//") || path.Contains('#'))
            throw new InvalidDataException();
        var route = path.Split('?')[0];
        string[] reads = { "/api/v1/manifest", "/api/v1/models", "/api/v1/providers", "/api/v1/skills",
            "/api/v1/skill-inventory", "/api/v1/projects", "/api/v1/extensions", "/api/v1/repositories",
            "/api/v1/rules", "/api/v1/context", "/api/v1/directory", "/api/dashboard", "/api/task-sync" };
        var body = value.GetProperty("body");
        if (!(method == "GET" && reads.Contains(route) && body.ValueKind == JsonValueKind.Null) &&
            !(method == "POST" && new[] { "/api/skill-activity", "/api/agent/report", "/api/task-sync/queue", "/api/task-sync/exchange", "/api/task-sync/resolve" }.Contains(route) &&
              path == route && body.ValueKind == JsonValueKind.Object)) throw new InvalidDataException();
        return value.Clone();
    }
    private static async Task<byte[]> Frame(Stream stream, int maximum, CancellationToken ct)
    {
        using var data = new MemoryStream();
        var one = new byte[1];
        while (data.Length < maximum)
        {
            if (await stream.ReadAsync(one, ct) == 0) throw new EndOfStreamException();
            if (one[0] == 10) return data.ToArray();
            data.WriteByte(one[0]);
        }
        throw new InvalidDataException("Frame limit");
    }
    private static async Task Write(Stream stream, byte[] bytes, CancellationToken ct)
    {
        if (bytes.Length >= ReplyLimit) throw new InvalidDataException("Reply limit");
        await stream.WriteAsync(bytes, ct); await stream.WriteAsync(new byte[] { 10 }, ct);
        await stream.FlushAsync(ct);
    }
    public void Start() => worker = Task.Run(Serve);
    private async Task Serve()
    {
        while (!stop.IsCancellationRequested)
        {
            try
            {
                using var pipe = new NamedPipeServerStream(name, PipeDirection.InOut, 1, PipeTransmissionMode.Byte,
                    PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly, 16384, 16384);
                await pipe.WaitForConnectionAsync(stop.Token);
                using var deadline = CancellationTokenSource.CreateLinkedTokenSource(stop.Token);
                deadline.CancelAfter(TimeSpan.FromSeconds(35));
                byte[] reply;
                try
                {
                    var raw = await Frame(pipe, RequestLimit, deadline.Token);
                    using var doc = JsonDocument.Parse(Utf8.GetString(raw), new JsonDocumentOptions { MaxDepth = 32 });
                    var result = await dispatch(Validate(doc.RootElement));
                    reply = JsonSerializer.SerializeToUtf8Bytes(new { ok = true, result });
                }
                catch { reply = JsonSerializer.SerializeToUtf8Bytes(new { ok = false, error = "request_rejected_or_outcome_unknown" }); }
                await Write(pipe, reply, deadline.Token);
            }
            catch (OperationCanceledException) when (stop.IsCancellationRequested) { break; }
            catch { if (!stop.IsCancellationRequested) await Task.Delay(100, stop.Token); }
        }
    }
    public void Dispose() { stop.Cancel(); }
    public static async Task<byte[]> Call(string name, byte[] raw)
    {
        if (raw.Length >= RequestLimit) throw new InvalidDataException();
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(40));
        using var pipe = new NamedPipeClientStream(".", name, PipeDirection.InOut, PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly);
        await pipe.ConnectAsync(3000, deadline.Token);
        await Write(pipe, raw, deadline.Token);
        return await Frame(pipe, ReplyLimit, deadline.Token);
    }
    public static async Task<int> Client(string config)
    {
        try
        {
            var raw = await Frame(Console.OpenStandardInput(), RequestLimit, CancellationToken.None);
            using var doc = JsonDocument.Parse(Utf8.GetString(raw)); Validate(doc.RootElement);
            var result = await Call(Name(config), raw);
            await Write(Console.OpenStandardOutput(), result, CancellationToken.None); return 0;
        }
        catch
        {
            await Write(Console.OpenStandardOutput(), JsonSerializer.SerializeToUtf8Bytes(new { ok = false, error = "application_unavailable_or_outcome_unknown" }), CancellationToken.None);
            return 2;
        }
    }
    public static async Task<int> SelfTest()
    {
        var count = 0; var name = "AgentCityAgent-test-" + Guid.NewGuid().ToString("N");
        using var server = new AgentPipe(name, request => { count++; return Task.FromResult(request.Clone()); });
        server.Start();
        var valid = Utf8.GetBytes("{\"method\":\"GET\",\"path\":\"/api/v1/context?cwd=synthetic\",\"body\":null}");
        using var accepted = JsonDocument.Parse(await Call(name, valid));
        using var rejected = JsonDocument.Parse(await Call(name, Utf8.GetBytes("{\"method\":\"GET\",\"path\":\"/api/state\",\"body\":null}")));
        using var duplicate = JsonDocument.Parse(await Call(name, Utf8.GetBytes("{\"method\":\"GET\",\"method\":\"POST\",\"path\":\"/api/state\",\"body\":null}")));
        var passed = accepted.RootElement.GetProperty("ok").GetBoolean() && !rejected.RootElement.GetProperty("ok").GetBoolean() &&
            !duplicate.RootElement.GetProperty("ok").GetBoolean() && count == 1;
        await Write(Console.OpenStandardOutput(), JsonSerializer.SerializeToUtf8Bytes(new { agentPipeSelfTest = passed, currentUserOnly = true, appStarted = false }), CancellationToken.None);
        return passed ? 0 : 2;
    }
}
