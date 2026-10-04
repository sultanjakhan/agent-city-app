# Bounded owner lifecycle review candidate

Extends frozen f824881; work/owner-bootstrap 74a4d6e and stable 5073787 remain
unchanged. NONINSTALLABLE pending independent review and native DOM/reload acceptance.
No live switch, migration, real auth/profile access, remote publication or OS
security/permission change. Startup v2 888d942 was inspected, not cherry-picked:
default owner launch does not use HTTP health probes or public PID as authority.

## Controller and authority

Default launch.py and both Start wrappers start a long-lived trusted native controller.
It retains its own server Popen handle and inherited anonymous stdin/stdout channels;
readiness binds nonce, retained child PID, checkout, port, owner hostname and local-only
mode. Windows socket binding is exclusive. All launches are local-only/no-refresh.
A new independent launcher cannot join/reuse a discovered server or issue a recovery
grant. Reopen/recovery/restart use the surviving trusted controller. Restart-AgentCity.ps1
only directs the user to Restart owned child there; it never probes or kills a port
owner. This is a deliberate authority-preserving handoff, not cross-shell automatic restart.
Mac native browser startup is explicitly refused before starting a server; not accepted.

Browser bootstrap is one-use/120 seconds. Session defaults are conservative proposal:
12 hour absolute and 2 hour idle expiry, NOT user-chosen policy. Trusted launch environment
can configure AGENT_CITY_OWNER_SESSION_TTL_SECONDS (3600..86400) and
AGENT_CITY_OWNER_SESSION_IDLE_SECONDS (300..14400, <= absolute). Invalid policy fails
closed. Caps are 256 bootstraps, 64 sessions and 128 CLI grants; authority is server RAM.
Explicit recovery revokes prior browser sessions and outstanding grants, issues a new
bootstrap and opens a new window without reloading existing DOM/drafts. Same-profile
windows can explicitly retry after the fresh session cookie is established.

CLI delegation is one-use/60 seconds, exact method/full path including query/canonical
JSON body digest. Enumerated context/dashboard reads and skill-activity/run-report POSTs
only; no general state/admin, credentials, cloud or Codex configuration grant. The
controller launches only its fixed city.py child and passes grant through stdin.
No grant file, persistent recovery key or public mint endpoint exists.

## Deadlines and retirement

One monotonic RPC budget spans mutex acquisition, pipe write and reply wait. Windows
uses a duplicated inherited pipe handle, raw WriteFile on an owned thread and
CancelSynchronousIo retry to close cancellation/start races; no buffered write/flush
lock is held on the GUI thread. POSIX uses nonblocking inherited FD/select. Ambiguous
delivery retires the channel and refuses further commands; EOF revokes/fences/drains
active admitted writes in the owned server. There is no silent command retry.
Messages are <=16 KiB, replies queued to at most eight, sequential/id/version checked;
only an identical immediately previous RPC can replay its cached response. HTTP grants
remain one-use. A known scope rejection does not poison a valid channel.

Start, CLI, recovery, restart and stop pass shared budgets through their internal steps.
Popen creation runs off the caller; timed-out late creation is cleaned only through the
new child's retained handle. Tk actions run off the GUI thread, disable duplicate actions
and display deadline failure without accepting a late success. Authority is retired on
GUI timeout. After an expired action the user may close only the controller, preserving
browser/profile for explicit review. OS scheduling/kernel calls, late cleanup and drain
of previously admitted writes are NOT hard real-time completion guarantees.

## Native Edge ownership and cleanup

Real Windows Edge exits its initial launcher and hands off to another browser process.
That process is adopted only if kernel snapshot identifies it as a direct msedge.exe
child of our retained initial process, and its creation lies between that parent's
kernel creation and exit times. A retained query/synchronize/terminate handle is then
held, not a rediscovered PID. Exact owner-origin title is also required to confirm the
browser window. Unknown parent/birth/handle or ambiguous candidates are refused.
These normal handle rights for the created child do not change privileges or ACLs.

The browser uses only its own fresh transient Temp profile. Focus/recovery require its
verified retained process plus exact owner title. Explicit close consent covers all
saved/closed drafts and this private browser process. WM_CLOSE targets only windows
of verified retained handles, with current HWND/PID/image revalidation. All retained
children must exit before profile cleanup. If windows remain, cleanup is refused.
If no visible owned window remains, the native controller's explicit close consent
permits terminating ONLY its retained windowless Edge background process, then waiting
for exit; this is recorded separately from graceful window close. No discovered PID
or unrelated browser process is terminated. GC/finalizer profile deletion is disabled;
only explicit verified cleanup removes the profile. Redirect metadata is refused.
Crash/failed ownership/unfinished cleanup can leave a QA/private browser profile.

## Evidence and remaining gates

Actual Tk buttons/protocol, Edge app windows, kernel-proven handoff, recovery to a second
owned window, new epoch restart, scoped CLI before/after and owned close/profile removal
passed on an isolated synthetic instance. Close needed explicit windowless background
termination. This is scoped native evidence, not full desktop acceptance.

Native UI Automation did not locate the expected authenticated DOM navigation control
or observe a new DOM after targeted reload; final attempt timed out (20 second phase).
Native DOM/session reload and multi-tab behavior remain UNVERIFIED. Headless tests cover
HTTP auth/reload/multitab/draft preservation but cannot replace that native proof.
No more native tool workarounds were attempted. Some failed synthetic QA profiles were
preserved; the first attempt lacked verified browser ownership and did not target another
PID. Independent security/QA review of pipe cancellation, handoff/birth proof, background
termination, deadline failure and wrappers is required. TTL/UX decisions and macOS native
acceptance remain open. Do not install or promote this checkpoint.

Cookies are not port-scoped; random hostname is not authentication. Browser-managed
cookies may exist on disk/restore and browser launch fragment is observable by powerful
same-account processes. No OS-principal isolation or browser-compromise guarantee is
made. Revoke does not undo already-admitted reads/writes. Broker loss drains only its
own server and cannot be repaired by publicly joining another process. Runtime and
credential/Codex path anchors are not migrated or copied by this implementation.


## Native oracle follow-up

Independent headed Edge renderer testing passed authenticated DOM/reload/multitab/
revoke-with-draft/recovery. The original phase20 RuntimeId-change/posted-F5 oracle was
invalid; it does not establish an auth/reload defect. The separate default-controller
window remains BLOCKED on supported DOM/document observation. Cold open/recovery
uses a conservative 30 second shared budget, explicit deadlines remain authoritative.
See NATIVE-CONTROLLER-ACCEPTANCE.md; no new driver or debugging transport is added.
