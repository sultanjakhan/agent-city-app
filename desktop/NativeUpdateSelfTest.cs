using System.Text.Json;

namespace AgentCityDesktop;

internal static class NativeUpdateSelfTest
{
    public static bool Run()
    {
        var clean = "{\"ready\":true,\"dirty\":false,\"unverifiedEdits\":false,\"pendingRequests\":0,\"openDialog\":false}";
        if (IdleClosePolicy.Deferral(clean) is not null) return false;
        foreach (var (input, reason) in new[] {
            ("null", "renderer-unavailable"), ("{}", "renderer-unavailable"),
            (clean.Replace("\"dirty\":false", "\"dirty\":true"), "unsaved-drafts"),
            (clean.Replace("\"unverifiedEdits\":false", "\"unverifiedEdits\":true"), "unverified-edits"),
            (clean.Replace("\"pendingRequests\":0", "\"pendingRequests\":1"), "requests-in-flight"),
            (clean.Replace("\"openDialog\":false", "\"openDialog\":true"), "open-dialog") })
            if (IdleClosePolicy.Deferral(input) != reason) return false;
        foreach (var valid in new[] {
            "{\"method\":\"GET\",\"path\":\"/api/desktop/update-status\",\"body\":null}",
            "{\"method\":\"POST\",\"path\":\"/api/desktop/update-check\",\"body\":{}}",
            "{\"method\":\"POST\",\"path\":\"/api/desktop/close-idle\",\"body\":{\"expectedSourceCommit\":\"" + new string('a', 40) + "\"}}" })
        {
            using var document = JsonDocument.Parse(valid);
            try { AgentPipe.Validate(document.RootElement); } catch { return false; }
        }
        foreach (var invalid in new[] {
            "{\"method\":\"GET\",\"path\":\"/api/desktop/update-status?x=1\",\"body\":null}",
            "{\"method\":\"POST\",\"path\":\"/api/desktop/update-check\",\"body\":{\"force\":true}}",
            "{\"method\":\"POST\",\"path\":\"/api/desktop/close-idle\",\"body\":{}}",
            "{\"method\":\"POST\",\"path\":\"/api/desktop/close-idle\",\"body\":{\"expectedSourceCommit\":\"bad\"}}",
            "{\"method\":\"POST\",\"path\":\"/api/desktop/close-idle\",\"body\":{\"expectedSourceCommit\":\"" + new string('a', 40) + "\",\"force\":true}}" })
        {
            using var document = JsonDocument.Parse(invalid);
            var rejected = false;
            try { AgentPipe.Validate(document.RootElement); } catch { rejected = true; }
            if (!rejected) return false;
        }
        return true;
    }
}
