# Owner bootstrap prototype — not installable acceptance

Branch work/owner-bootstrap descends from immutable 0336c5e. The baseline and its
report are unchanged. ce2aadb is a separately cherry-pickable fix for malformed
persisted agent/status types, including a 35-case store matrix. The prototype also
checks the same 35 cases through HTTP dashboard/cloud projection; no invalid file
is rewritten.

## Implemented and bounded

Server always requires an in-memory owner session for every /api/ read and write,
including v1 aliases. Only minimal health and one-use bootstrap are public. Health
contains appId/version/localOnly, no paths or token. Host/Origin and browser CSRF
checks remain. A public local client cannot fetch csrfToken or authorize itself.

Trusted launcher creates random 256-bit capability and a random .localhost owner
origin, gives them to the child through its private environment, and opens the app
with capability in URL fragment. No capability in command-line server arguments,
server output, application config, credential file or export. The browser strips
the fragment before application API calls and exchanges it once, within two minutes,
for HttpOnly/SameSite=Strict session cookie without Expires/Max-Age. Authority stores
only hashes in memory; restart invalidates prior grants. Browser cookies are browser
managed and may be retained by session restore; no claim is made that browser
internals never write session cookies to disk. They never become permanent server
credentials. No localStorage/sessionStorage secret or OS/security-setting change.

The random owner origin binds authorization as well as cookie host. Ordinary
127.0.0.1/localhost services on another port do not receive its cookie. This does not
protect against a powerful same-account process reading browser/process memory or
against browser compromise. .localhost resolves internally in tested Chromium; other
browser/platform behavior requires separate acceptance.

All fixtures authenticate through the actual one-use HTTP endpoint. There is no
server auth-disable/test bypass. Python/native API clients connect to 127.0.0.1 with
the issued logical Host/Origin; Chromium uses the actual owner origin. Cookie/session
values stay in test memory. Playwright traces are disabled to prevent session-bearing
trace retention. No storage-state file is generated.

## Confirmed lifecycle gaps: do not install

1. A new launcher can focus an existing window, but cannot safely mint a fresh grant
   for an already-running server when the browser session is lost. It returns a
   clear error and issues no public reconnect capability. The existing dialog's
   Retry works only once a legitimate session has become available; it never
   authorizes an unknown caller.
2. city.py previously fetched a public CSRF token. It is now denied explicitly;
   delegated CLI grants have not been designed. The former CLI report-use test was
   changed to verify refusal and absence of invented activity, not to claim CLI
   functionality is preserved.
3. Restart-AgentCity.ps1 cannot read protected state without owner authorization.
   It now stops with a clear error before process termination. Its earlier unattended
   restart workflow is not supported by this prototype. No process is stopped to
   recover a lost session automatically.
4. Window reuse currently identifies title/process class rather than an owner
   origin/checkout session. Actual desktop launch/restart could focus the installed
   live window. Only synthetic child startup with browser-open interception and
   genuine headless browser rendering were tested; no live desktop was touched.

A safe complete lifecycle needs an explicit owner-authorized restart/reconnect and
narrow CLI delegation contract, plus origin-specific window identity. Options are a
long-lived trusted launcher retaining a private inherited channel, or an authenticated
owner UI that explicitly authorizes narrowly scoped child commands/restart. The
existing public health endpoint must not become a new grant-discovery endpoint.
Do not restore public token bootstrap to keep old utilities working. Persistent
credentials, new IPC/ACL rules or principal-security claims require separate scope.

## Paired migration boundary

Stable migration remains inactive. The reviewed migration handoff requires the
updated stable_migration.py hash from recoverability-acceptance.json, exact pointer
backup/candidate validation, declared actual path environment overrides, verified
quiescence and a single coordinated pointer writer. Its draft currently selects
only ordinary skills/global copies; runtime stays at its existing location and
credential/Codex anchors remain pinned. No copy, prepare/install, pointer switch,
process stop or migration rollback was performed here. Interrupted rollback needs
explicit recovery/quarantine review; no automatic merge. Auth/session/draft closure
must be resolved before a paired restart or migration can be accepted.

## Checkpoint evidence

294 Python tests pass (9 platform/fixture skips), including real launcher child
startup/reuse/failed lost-window recovery, owner HTTP refusal/bootstrap and the
35-case HTTP malformed run matrix. Three browser auth lifecycle tests pass.
Full Chrome suite: 98/100 pass; two harness issues were corrected (tooltip expected
old #222 after shared token changed to #252525, and pending-preview release callback
was used before its route arrived). Their focused rerun is recorded separately.
Syntax and diff checks pass. Full production lifecycle acceptance is blocked by the
four gaps above even when regression tests pass. No actual desktop, live credentials,
provider inference, server install or pointer migration was performed.
