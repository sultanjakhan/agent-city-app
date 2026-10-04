using System;
using System.Threading.Tasks;
using AgentCityDesktop;

internal static class NativeLocaleContract
{
    public static async Task<int> Main()
    {
        var locale = new DesktopLocale();
        long document = 1;
        if (locale.CopyFor(nameof(DesktopText.Recover), document, epoch => epoch == document) != null) throw new Exception("Invented startup locale");
        foreach (var language in new[] { "ru", "en" })
        {
            var response = "{\"version\":1,\"language\":\"" + language + "\"}";
            if (!await locale.ReadAsync(script =>
                { if (script != DesktopLocale.SnapshotScript) throw new Exception("Unexpected script"); return Task.FromResult(response); },
                document, epoch => epoch == document)) throw new Exception("Valid propagation refused");
            if (locale.CopyFor(nameof(DesktopText.Recover), document, epoch => epoch == document) != DesktopText.ForLanguage(nameof(DesktopText.Recover), language))
                throw new Exception("Native copy differs from effective web language");
        }
        foreach (var invalid in new[] { "null", "{}", "\"en\"", "[]", "{\"version\":1,\"language\":\"fr\"}",
            "{\"version\":2,\"language\":\"ru\"}", "{\"version\":1,\"language\":\"ru\",\"extra\":0}",
            "{\"version\":1,\"language\":\"ru\",\"language\":\"en\"}", "malformed", new string('x', 65) })
        {
            if (await locale.ReadAsync(_ => Task.FromResult(invalid), document, epoch => epoch == document))
                throw new Exception("Invalid snapshot accepted");
            if (locale.LanguageFor(document) != "en") throw new Exception("Invalid response invented a fallback");
        }
        var reads = 0;
        var invalidated = new TaskCompletionSource<string>();
        var invalidatedRead = locale.ReadAsync(_ => invalidated.Task, document, epoch => epoch == document);
        locale.Invalidate();invalidated.SetResult("{\"version\":1,\"language\":\"ru\"}");
        if (await invalidatedRead || locale.LanguageFor(document) != null)
            throw new Exception("Explicit new-document invalidation retained a response at the same epoch");
        if (!await locale.ReadAsync(_ => Task.FromResult("{\"version\":1,\"language\":\"en\"}"), document, epoch => epoch == document))
            throw new Exception("Valid read after invalidation refused");
        var older = new TaskCompletionSource<string>();
        var olderRead = locale.ReadAsync(_ => older.Task, document, epoch => epoch == document);
        if (!await locale.ReadAsync(_ => Task.FromResult("{\"version\":1,\"language\":\"en\"}"), document, epoch => epoch == document))
            throw new Exception("Newer snapshot refused");
        older.SetResult("{\"version\":1,\"language\":\"ru\"}");
        if (await olderRead || locale.LanguageFor(document) != "en") throw new Exception("Older read overwrote a newer snapshot");
        if (await locale.ReadAsync(_ => { reads++; return Task.FromResult("null"); }, document, _ => false) || reads != 0)
            throw new Exception("Out-of-scope document read");
        var pending = new TaskCompletionSource<string>();
        var read = locale.ReadAsync(_ => pending.Task, document, epoch => epoch == document);
        document++;
        pending.SetResult("{\"version\":1,\"language\":\"ru\"}");
        if (await read || locale.CopyFor(nameof(DesktopText.Recover), document, epoch => epoch == document) != null)
            throw new Exception("Late response crossed document boundary");
        if (!await locale.ReadAsync(_ => Task.FromResult("{\"version\":1,\"language\":\"ru\"}"), document, epoch => epoch == document))
            throw new Exception("New document snapshot refused");
        if (locale.CopyFor(nameof(DesktopText.Recover), document, _ => false) != null)
            throw new Exception("Copy exposed outside the current document scope");
        bool originValid = true;
        var lostOrigin = new TaskCompletionSource<string>();
        var originRead = locale.ReadAsync(_ => lostOrigin.Task, document, epoch => epoch == document && originValid);
        originValid = false;
        lostOrigin.SetResult("{\"version\":1,\"language\":\"en\"}");
        if (await originRead || locale.LanguageFor(document) != "ru") throw new Exception("Origin loss accepted a response");
        if (await locale.ReadAsync(_ => Task.FromException<string>(new Exception("synthetic unavailable")), document, epoch => epoch == document))
            throw new Exception("Unavailable renderer accepted");
        var never = new TaskCompletionSource<string>();
        if (await locale.ReadAsync(_ => never.Task, document, epoch => epoch == document))
            throw new Exception("Read deadline did not refuse an unavailable response");
        never.SetResult("{\"version\":1,\"language\":\"en\"}");
        if (locale.LanguageFor(document) != "ru") throw new Exception("Late timeout response changed copy");
        Console.WriteLine("PASS read-only locale adapter: RU/EN copy propagation, strict snapshot, no invented fallback, stale-document rejection; actual CityWindow methods tested separately");
        return 0;
    }
}
