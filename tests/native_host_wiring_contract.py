"""Compile actual host presentation methods against no-window test doubles."""
from pathlib import Path
import argparse
import re
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]


def body(source, start):
    opening = source.index('{', start)
    depth, quoted, escape = 0, None, False
    for end in range(opening, len(source)):
        ch = source[end]
        if quoted:
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == quoted:
                quoted = None
        elif ch in ('"', "'"):
            quoted = ch
        elif ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if not depth:
                return source[start:end+1]
    raise AssertionError('Unbalanced source contract')


def method(source, name):
    match = re.search(r'    private [^\n]*?\b' + name + r'\(', source)
    assert match, name
    start = match.start()
    if name == 'NativeText':
        return source[start:source.index(';', start)+1]
    return body(source, start)


def baseline():
    return json.loads((ROOT / 'tests/fixtures/native-copy-baseline.json').read_text('utf8'))


def generate(output):
    source = (ROOT / 'desktop/Program.cs').read_text('utf8')
    reference = baseline()
    original = reference['host']
    # Prove that copy wiring leaves actual broker/authority/recovery code intact.
    for name in ('WirePolicy', 'PrivateBridge'):
        token = 'internal ' + ('static' if name == 'WirePolicy' else 'sealed') + ' class ' + name
        assert body(source, source.index(token)) == body(original, original.index(token)), name
    assert method(source, 'Bootstrap').replace('SetStatus(nameof(DesktopText.RecoveryReady))',
        'status.Text = DesktopText.RecoveryReady') == method(original, 'Bootstrap')
    assert method(source, 'ObserveBackend').replace('SetStatus(nameof(DesktopText.BackendUnavailable))',
        'status.Text = DesktopText.BackendUnavailable') == method(original, 'ObserveBackend')
    original_failure = re.search(r'catch \{ status.Text = ("(?:[^"\\]|\\.)*"); \}', method(original, 'Action'))[1]
    assert method(source, 'Action').replace('SetStatus(nameof(DesktopText.ActionFailed))',
        'status.Text = ' + original_failure) == method(original, 'Action')
    original_close = method(original, 'OnClosing')
    question = re.search(r'ConfirmDrafts\(("(?:[^"\\]|\\.)*")\)', original_close)[1]
    drain = re.search(r'catch \{ closing = false; status.Text = ("(?:[^"\\]|\\.)*");', original_close)[1]
    normalized_close = method(source, 'OnClosing').replace('await ConfirmDrafts(nameof(DesktopText.CloseQuestion))',
        'ConfirmDrafts(' + question + ')').replace('localeRefresh.Stop(); ', '').replace(
        'SetStatus(nameof(DesktopText.DrainPending))', 'status.Text = ' + drain)
    update_start = normalized_close.index('            updater?.Dispose();')
    update_end = normalized_close.index('            approvedClose = true; Close();', update_start)
    normalized_close = normalized_close[:update_start] + normalized_close[update_end:]
    assert normalized_close == original_close
    for unchanged in ['desktop/RecoveryScripts.cs', 'desktop/recovery.js', 'static/owner-session.js',
                      'static/i18n.js', 'static/work-registry.js']:
        assert hashlib.sha256((ROOT / unchanged).read_text('utf8').encode()).hexdigest() == reference['unchangedSha256'][unchanged], unchanged
    current_script = (ROOT / 'desktop/DesktopLocale.cs').read_text('utf8')
    assert re.search(r'SnapshotScript = .*?;', current_script)[0] == reference['snapshotScript']
    for setting in ['AreHostObjectsAllowed = false', 'IsWebMessageEnabled = false',
                    'AreDevToolsEnabled = false', 'AreBrowserAcceleratorKeysEnabled = false']:
        assert setting in source
    assert 'localeRefresh.Tick += async (_, _) => { if (!busy && (localeReadTask == null || localeReadTask.IsCompleted)) await RefreshNativeLocale(); };' in source
    assert 'localeRefresh.Stop();' in source and 'localeRefresh.Dispose();' in source
    assert 'await RefreshNativeLocale();' in method(source, 'ConfirmDrafts')
    assert 'MessageBoxButtons.YesNo, MessageBoxIcon.Question) == DialogResult.Yes' in method(source, 'ConfirmDrafts')
    assert '!await ConfirmDrafts(nameof(DesktopText.RestartQuestion))' in source
    assert 'loaded && !await ConfirmDrafts(nameof(DesktopText.CloseQuestion))' in source
    assert len(re.findall(r'bridge\.Command\("', source)) == len(re.findall(r'bridge\.Command\("', original))
    assert len(re.findall(r'bridge\.Start\(', source)) == len(re.findall(r'bridge\.Start\(', original))
    assert re.findall(r'bridge\.Command\("[^)]*\)', source) == re.findall(r'bridge\.Command\("[^)]*\)', original)
    actual = '\n'.join(method(source, name).replace('private ', 'internal ', 1)
        for name in ['IsCurrentLocaleDocument', 'NativeText', 'RenderNativeCopy', 'RenderStatus', 'SetStatus',
                     'RefreshNativeLocale', 'ReadNativeLocale', 'ConfirmDrafts'])
    starting = body(source, source.index('core.NavigationStarting +=')).split('=>', 1)[1].strip()
    completed = body(source, source.index('core.NavigationCompleted +=')).split('=>', 1)[1].strip()
    changed = body(source, source.index('core.SourceChanged +=')).split('=>', 1)[1].strip()
    wire = body(source, source.index('internal static class WirePolicy'))
    stub = r'''
using System;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Security.Cryptography;
using System.Threading.Tasks;
namespace AgentCityDesktop;
internal sealed class FakeCore
{
    internal bool ThrowSource;
    private string source = "http://agent-city-" + new string('a',32) + ".localhost:12345/";
    internal string Source { get { if(ThrowSource) throw new Exception("synthetic unavailable"); return source; } set {source=value;} }
    internal int Reads;
    internal Func<Task<string>> Reader = () => Task.FromResult("{\"version\":1,\"language\":\"en\"}");
    internal Task<string> ExecuteScriptAsync(string script)
    {
        if(script != DesktopLocale.SnapshotScript) throw new Exception("Non-read-only script");
        Reads++; return Reader();
    }
}
internal sealed class FakeView { internal bool IsDisposed; internal FakeCore CoreWebView2 = new(); }
internal sealed class FakeText { internal string Text = ""; internal bool Enabled=true; }
internal sealed class FakeBridge { internal Uri? Origin = new("http://agent-city-" + new string('a',32) + ".localhost:12345/"); }
internal sealed class Starting { internal string Uri = ""; internal ulong NavigationId; internal bool Cancel; }
internal sealed class Completed { internal ulong NavigationId; internal bool IsSuccess; }
internal sealed class Changed { internal bool IsNewDocument; }
internal enum MessageBoxButtons { YesNo }
internal enum MessageBoxIcon { Question }
internal enum DialogResult { Yes, No }
internal static class MessageBox
{
    internal static int Calls;
    internal static string LastText = "";
    internal static DialogResult Result = DialogResult.Yes;
    internal static DialogResult Show(object owner,string text,string title,MessageBoxButtons buttons,MessageBoxIcon icon)
    { Calls++; LastText=text; return Result; }
}
internal sealed class FakeWindowMenu { internal void Refresh() {} }
internal sealed class CityWindow
{
    internal readonly FakeView view = new();
    internal readonly FakeBridge bridge = new();
    internal readonly FakeText recover = new(), restart = new(), revoke = new(), status = new(), checkUpdates = new();
    internal FakeWindowMenu? windowMenu;
    internal string? pendingUpdateVersion;
    internal FakeCore? localeCore;
    internal bool IsDisposed, busy, closing, confirmationBusy;
    internal Task? localeReadTask;
    internal long localeReadEpoch=-1;
    internal long documentEpoch, completedEpoch = -1;
    internal ulong localeNavigationId;
    internal bool localeDocumentLoaded;
    internal readonly DesktopLocale locale = new();
    internal string statusKey = nameof(DesktopText.Starting);
    internal CityWindow() { localeCore=view.CoreWebView2; }
'''
    harness = r'''
}
internal static class NativeHostWiringContract
{
    static void Check(bool result,string category) { if(!result) throw new Exception(category); }
    public static async Task<int> Main()
    {
        var host=new CityWindow(); var core=host.view.CoreWebView2;
        await host.RefreshNativeLocale(); Check(core.Reads==0,"Read before successful document");
        await host.SourceChanged(new Changed{IsNewDocument=false});Check(core.Reads==0,"Early same-document event invented readiness");
        var rejected=new Starting{Uri="https://synthetic.invalid/",NavigationId=1};host.NavigationStarting(rejected);
        Check(rejected.Cancel&&host.documentEpoch==0,"Out-of-origin navigation accepted");
        host.NavigationStarting(new Starting{Uri=core.Source,NavigationId=2});
        await host.NavigationCompleted(new Completed{NavigationId=1,IsSuccess=true});Check(core.Reads==0,"Old navigation completion accepted");
        await host.NavigationCompleted(new Completed{NavigationId=2,IsSuccess=false});Check(core.Reads==0,"Failed navigation became ready");
        await host.NavigationCompleted(new Completed{NavigationId=2,IsSuccess=true});
        Check(host.recover.Text=="Recover access"&&host.status.Text==DesktopText.ForLanguage(nameof(DesktopText.Starting),"en"),"Actual host EN rendering");
        host.NavigationStarting(new Starting{Uri=core.Source+"#repos",NavigationId=4});await host.SourceChanged(new Changed{IsNewDocument=false});
        Check(host.locale.LanguageFor(host.documentEpoch)=="en","Successful retained fragment document lost locale");
        await host.SourceChanged(new Changed{IsNewDocument=true});
        Check(host.locale.LanguageFor(host.documentEpoch)==null,"A new document reused locale accepted at its pending-navigation epoch");
        await host.NavigationCompleted(new Completed{NavigationId=4,IsSuccess=true});
        host.SetStatus(nameof(DesktopText.AccessRevoked));Check(host.status.Text==DesktopText.ForLanguage(nameof(DesktopText.AccessRevoked),"en"),"Status did not use locale");
        core.Reader=()=>Task.FromResult("{\"version\":1,\"language\":\"ru\"}");await host.RefreshNativeLocale();
        Check(host.recover.Text==DesktopText.Recover&&host.status.Text==DesktopText.AccessRevoked,"Actual host RU switch");
        Check(await host.ConfirmDrafts(nameof(DesktopText.RestartQuestion)),"RU confirmation result");
        Check(MessageBox.LastText==DesktopText.SaveDrafts+DesktopText.RestartQuestion,"Actual RU confirmation copy");
        core.Reader=()=>Task.FromResult("{\"version\":1,\"language\":\"en\"}");
        Check(await host.ConfirmDrafts(nameof(DesktopText.CloseQuestion)),"EN confirmation result");
        Check(MessageBox.LastText==DesktopText.ForLanguage(nameof(DesktopText.SaveDrafts),"en")+DesktopText.ForLanguage(nameof(DesktopText.CloseQuestion),"en"),"Actual EN confirmation copy");
        MessageBox.Result=DialogResult.No;Check(!await host.ConfirmDrafts(nameof(DesktopText.CloseQuestion)),"No changed to Yes");MessageBox.Result=DialogResult.Yes;
        foreach(var invalid in new[]{"null","{\"version\":1,\"language\":\"fr\"}","malformed"})
        {core.Reader=()=>Task.FromResult(invalid);await host.RefreshNativeLocale();Check(host.locale.LanguageFor(host.documentEpoch)=="en","Unknown language invented fallback");}
        var reads=core.Reads;host.busy=true;await host.RefreshNativeLocale();host.busy=false;Check(core.Reads==reads,"Locale read overlapped auth action");
        core.Source="http://agent-city-"+new string('b',32)+".localhost:12345/";await host.RefreshNativeLocale();
        Check(core.Reads==reads&&!host.IsCurrentLocaleDocument(host.documentEpoch),"Wrong private origin read");
        Check(host.NativeText(nameof(DesktopText.Recover))==DesktopText.Recover,"Unknown scope did not preserve explicit legacy unlocalized copy");
        core.Source=host.bridge.Origin!.ToString();host.view.CoreWebView2=new FakeCore();await host.RefreshNativeLocale();Check(core.Reads==reads,"Replaced WebView read");host.view.CoreWebView2=core;
        core.ThrowSource=true;await host.RefreshNativeLocale();Check(core.Reads==reads,"Disposed core property was used");core.ThrowSource=false;
        var pending=new TaskCompletionSource<string>();core.Reader=()=>pending.Task;var stale=host.RefreshNativeLocale();
        host.NavigationStarting(new Starting{Uri=core.Source,NavigationId=3});
        await host.SourceChanged(new Changed{IsNewDocument=true});Check(!host.IsCurrentLocaleDocument(host.documentEpoch),"New document became ready before completion");
        var fresh=new TaskCompletionSource<string>();core.Reader=()=>fresh.Task;
        var completion=host.NavigationCompleted(new Completed{NavigationId=3,IsSuccess=true});
        pending.SetResult("{\"version\":1,\"language\":\"ru\"}");await stale;
        Check(host.locale.LanguageFor(host.documentEpoch)==null,"Actual host stale navigation response accepted");
        fresh.SetResult("{\"version\":1,\"language\":\"en\"}");await completion;
        core.Reader=()=>Task.FromResult("{\"version\":1,\"language\":\"en\"}");await host.RefreshNativeLocale();Check(host.locale.LanguageFor(host.documentEpoch)=="en","New document refresh");
        var never=new TaskCompletionSource<string>();core.Reader=()=>never.Task;await host.RefreshNativeLocale();
        Check(host.localeReadTask!.IsCompleted&&host.locale.LanguageFor(host.documentEpoch)=="en","Timeout changed locale or wedged refresh");
        never.SetResult("{\"version\":1,\"language\":\"ru\"}");Check(host.locale.LanguageFor(host.documentEpoch)=="en","Late timeout changed host copy");
        var confirmation=new TaskCompletionSource<string>();core.Reader=()=>confirmation.Task;var first=host.ConfirmDrafts(nameof(DesktopText.CloseQuestion));var calls=MessageBox.Calls;
        Check(!host.recover.Enabled&&!host.restart.Enabled&&!host.revoke.Enabled,"Native actions active during pending confirmation");
        Check(!await host.ConfirmDrafts(nameof(DesktopText.CloseQuestion)),"Confirmation reentered while read pending");host.closing=true;
        confirmation.SetResult("{\"version\":1,\"language\":\"en\"}");Check(!await first&&MessageBox.Calls==calls,"Dialog shown after closing");
        host.closing=false;host.IsDisposed=true;reads=core.Reads;await host.RefreshNativeLocale();Check(core.Reads==reads,"Disposed window read");
        host.IsDisposed=false;host.view.IsDisposed=true;await host.RefreshNativeLocale();Check(core.Reads==reads,"Disposed WebView read");
        Console.WriteLine("PASS actual CityWindow methods/hooks on no-window doubles: origin/retained-core/ready-epoch checks, RU-EN-RU menus/status/confirm, stale navigation, timeout, unknown locale, confirmation guards; no auth adapter");
        return 0;
    }
}
'''
    output.write_text(stub + actual + '\ninternal void NavigationStarting(Starting e) ' + starting +
        '\ninternal async Task NavigationCompleted(Completed e) ' + completed +
        '\ninternal async Task SourceChanged(Changed e) ' + changed + harness + '\n' + wire, encoding='utf8')
    print('PASS source contracts: unchanged broker/recovery/health authority, fixed snapshot, web permissions, bounded UI timer, confirm gates')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    generate(parser.parse_args().output)
