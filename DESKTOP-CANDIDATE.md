# Windows desktop candidate — not installed or accepted

Base owner/auth/native-oracle 8aba5cca49cec609452cbe4ff334a4af5b529b78.
This changes the host, not the existing web UI or user data. Do not install until
independent QA and the active stable/UI integration review pass.

One WinForms/WebView2 window hosts the existing application. It creates no Tk
controller or standalone Edge app window. A per-user existing-panel filesystem identity scoped
Windows mutex owns its lifetime. Mode/config-specific focus events refuse
conflicting launches instead of silently focusing another runtime. Different
configs sharing the panel cannot create a second desktop backend. Local reparse
and network profile paths are refused, not silently canonicalized or imported. An exact matching subsequent launch signals only focus through a
named local event, with no authority or server discovery. The host never closes,
focuses by title, reuses or kills unknown windows/processes.

The host starts one retained backend bridge with inherited private pipes. The
bridge reuses OwnerBroker and its private server control/auth protocol. Frozen
script dispatch replaces Python script subprocess commands; Python is included.
An OS-selected exclusive loopback port avoids touching an occupied production
port. Readiness is accepted only from the inherited own-child pipe, with exact
PID/root/epoch/origin/runtime checks; no public HTTP/PID assertion authorizes reuse.
Normal runtime is explicit for desktop launch; existing launcher behavior remains
local-only by default. Startup still uses --no-refresh. Configured normal-runtime
cloud/background jobs retain their existing behavior and must be checked in QA.
No current profile, credential store, production port or running app was used.

Navigation/resources stay on the owned random .localhost origin. Host objects,
web messaging, external windows, downloads and native web permissions are denied;
no debug/CDP listener or security bypass is enabled. Native menu actions use the
private pipe. Bootstrap is a removed URL fragment on first navigation. Reauth
exchanges a fresh capability on the exact existing origin without navigating the
current DOM. The injected start returns a synchronous primitive; a nonce/document
marker is polled for a finished primitive under a bounded deadline. Failure revokes
ambiguous authority and clears the marker, without web messaging or sync XHR; the user explicitly retries the UI. Mutations are not replayed.
Backend exit/control loss keeps the window open. A serialized private status check with a 3-second budget
queries own server-child liveness through the bridge, not proof of HTTP responsiveness. Restart and
close require explicit draft closure; no automatic restart/reload discards drafts.
Host EOF uses existing server revoke/fence/drain behavior; no forced write-time kill.
Renderer crash cannot guarantee preservation of renderer memory; this is a separate
failure mode to verify and explain, not a claimed fixed cause of prior disappearances.

Each launch uses an isolated temporary WebView profile, separate from product data.
Cleanup occurs only after managed BrowserProcessExited, under the exact generated
Temp directory and with recursive reparse rejection. Unconfirmed exit preserves
the temporary profile. No existing browser profile/auth session store is read.

Current QA command (only with a verified visible interactive session):

    AgentCity.exe --config <explicit-synthetic-storage.json> --local-only

Normal mode omits --local-only. The executable also supports --self-test with zero
windows/server startup. Backend/AgentCityBackend.exe --self-test verifies the frozen
bundle without starting a backend. The package needs Windows x64, .NET Desktop
10 and WebView2 Runtime; both runtimes exist on this execution machine. It does not
install runtimes or elevate at startup. Package is unsigned, no publisher claim.

Ordinary installed launch will use adjacent desktop-profile.json with a configFile
pointer to the explicitly confirmed EXISTING external storage config. No data
folder chooser, implicit discovery/import or embedded personal path is provided.
Pointer file is installation-specific and absent from public candidate. Validate
the effective original storage paths and environment overrides before making this
pointer: blindly using an incomplete config could select an empty profile. Data
stays outside binaries; no migration is authorized or included.

Offline build (after fixed build tools/packages are prepared in owned build root):

    python tools/build_desktop.py --build-root <workspace-build-root>

Dependencies: PyInstaller6.22.3 and Microsoft.Web.WebView2 SDK1.0.3537.50; NuGet lock
is checked in. Each build uses fresh compiler/frozen outputs and a new staging directory. Only
exact host outputs and the frozen COLLECT allowlist are copied; assets come from
tracked source files with verified hashes, not directory globs. Unknown outputs
fail before publish. Manifest matches the exact staged copy set and source commit.
Atomic publication uses a unique absent candidate directory. Existing candidates,
unknown logs, pointers and stale DLLs are preserved and never reused or deleted.
Build intermediates, tools, logs and personal config are not packaged.
Candidate manifest hashes all packaged public binary/assets/license files. Build
uses disabled .NET telemetry/first-run/certificate flags and workspace CLI home.
The initial SDK invocation had already reported automatic development-certificate
creation before these flags were applied. No trust command, certificate-store read
or certificate removal was performed; report this build-side effect separately.

## Remaining acceptance and installation work

- Independent source/security review of bridge, normal runtime, origin/lifecycle,
  package allowlist, single-instance event and cleanup. Normal mode must preserve
  auth/owner enforcement; it is not a grant to use provider credentials in QA.
- Visible synthetic native QA: meaningful populated DOM, double launch focus,
  actual reload, revoke/draft preservation, explicit reauth/retry, backend loss
  leaving window/drafts, restart, close/drain/profile cleanup, no external requests.
  No current window has been launched: interactive enumeration access is blocked.
- Review latest stable/UI/settings changes against this owner base before choosing
  a final release. Packaging an older base is not acceptance of current features.
- Confirm exact existing storage/profile and runtime paths, take a restorable backup
  via separately approved installation scope, then install versioned binaries and
  Start-menu/Desktop shortcuts with rollback. Never replace data, switch to an empty
  profile, stop an unknown backend or close unknown windows. No install was attempted.
- Investigate current stability only through new candidate acceptance; do not claim
  the cause of earlier lag/logout/disappearing windows was identified or fixed.

## Review-finding regressions (author tests; native acceptance still pending)

D01: five real filesystem packaging tests (build subprocesses not invoked) verify
fresh publication, old private/stale files preserved/excluded, exact manifest hashes
and rejection of unknown/missing outputs. Seven fixed wheel hashes/license sources
and the NuGet lock constrain build inputs. Tracked public assets exclude vendor
__pycache__ and any untracked runtime file. No unknown file is deleted to clean up.
D02: six Node VM tests run the actual recovery resource with fake fetch/clock,
checking synchronous start, success/refusal, expiry/late responses, operation and
document replacement, draft identity and no request replay. Compiled host selftest
rejects Promise-object/bool JSON and accepts only explicit primitive states. This
is JS/contract verification, not a real WebView cookie/native recovery result.
D03: bridge test returns alive then dead server while bridge remains active; compiled
BackendHealth observes dead child and the host timer calls private status. This
proves dispatch/state behavior, not a visible native failure-injection result.
D04: C# source strings are ASCII with Unicode escapes after lossless mojibake repair;
compiled label checks and source Unicode tests verify intended Russian codepoints.
Visible font/rendering/accessibility is still a native QA gate.
D05: compiled no-window selftest uses real Windows focus events to prove mismatched
mode/config cannot signal the existing event, and metadata of two synthetic configs
proves a shared panel identity. Actual double-launch window/focus is not accepted.
Network/reparse profile mappings are conservatively refused. Existing legacy Python
launchers do not implement this panel mutex: before installing, the old runtime must
be quiescent through its verified owner, without PID/title guessing or data sharing.
