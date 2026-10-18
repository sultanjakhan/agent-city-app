using System.Text.Json;

namespace AgentCityDesktop;

// Renderer observations are deliberately fail-closed. No renderer text is returned to callers.
internal static class IdleClosePolicy
{
    public const string InstallScript = """
    (() => {
      if (window.top !== window || window.__agentCityIdleClose) return;
      const baselines = new WeakMap(), edits = new Map();
      let pending = 0;
      const value = n => n.type === 'checkbox' || n.type === 'radio' ? n.checked : n.multiple && n.selectedOptions ? JSON.stringify([...n.selectedOptions].map(o => o.value)) : n.isContentEditable ? n.textContent : n.value;
      const editable = n => n && (n.matches?.('input,textarea,select') || n.isContentEditable);
      document.addEventListener('focusin', e => { if (editable(e.target) && !baselines.has(e.target)) baselines.set(e.target, value(e.target)); }, true);
      for (const kind of ['input', 'change']) document.addEventListener(kind, e => {
        const n = e.target;
        if (!editable(n)) return;
        if (!baselines.has(n)) { edits.set(n, { unknown: true }); return; }
        edits.set(n, { initial: baselines.get(n) });
      }, true);
      const fetch = window.fetch;
      window.fetch = function(...args) {
        pending++;
        try { return Promise.resolve(fetch.apply(this, args)).finally(() => pending--); }
        catch (error) { pending--; throw error; }
      };
      window.__agentCityIdleClose = Object.freeze({ snapshot() {
        const event = new Event('beforeunload', { cancelable: true });
        window.dispatchEvent(event);
        let unsent = false;
        try { unsent = Object.keys(JSON.parse(localStorage.getItem('agent-city-shared-unsent-v1') || '{}')).length > 0; }
        catch { return { ready: false }; }
        return { ready: document.readyState === 'complete', dirty: event.defaultPrevented || unsent,
          unverifiedEdits: [...edits].some(([n, before]) => before.unknown || value(n) !== before.initial),
          pendingRequests: pending, openDialog: !!document.querySelector('dialog[open]') };
      } });
    })();
    """;

    public const string SnapshotScript = "window.__agentCityIdleClose ? window.__agentCityIdleClose.snapshot() : null";

    public static string? Deferral(string encoded)
    {
        try
        {
            using var document = JsonDocument.Parse(encoded);
            var value = document.RootElement;
            if (value.ValueKind != JsonValueKind.Object || !value.GetProperty("ready").GetBoolean()) return "renderer-unavailable";
            if (value.GetProperty("dirty").GetBoolean()) return "unsaved-drafts";
            if (value.GetProperty("unverifiedEdits").GetBoolean()) return "unverified-edits";
            if (value.GetProperty("pendingRequests").GetInt32() != 0) return "requests-in-flight";
            if (value.GetProperty("openDialog").GetBoolean()) return "open-dialog";
            return null;
        }
        catch { return "renderer-unavailable"; }
    }
}
