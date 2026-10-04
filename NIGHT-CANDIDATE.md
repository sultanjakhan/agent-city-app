# Night candidate 0.5.19

Isolated branch `work/registry-consumer`; installed main remains 0.5.18.
No live pointer, runtime, database, credential or server installation changes.

Changes: explicit published registry/report consumer with source-profile pairing,
dynamic dashboard refresh and legacy report aliases; recoverable policy conflicts;
repository discovery on reopen; refreshed pipeline chooser preserving draft;
single pending pipeline save with disabled mutating controls; shared neutral tokens
and persistent light/dark/system appearance without navigation regrouping; metadata
private-file guards; strict persisted run validation and outgoing allowlists.

N01-N04 synthetic regressions pass. Theme checks cover real application views at
390/760/1280 widths, light/dark/system, persistence and page errors; screenshots
are QA evidence, not a claim of owner visual acceptance. Shared-neutral.css is the
unchanged UX handoff token file. Cicada native/Mac theme acceptance is separate.

Security AC2: invalid stored top-level/run/history fields fail closed before
projection; dashboard gives a generic error, cloud projection raises without
sending, and invalid files are not erased or migrated. Explicit outgoing allowlists
are additional protection. Existing valid report reopen/sequence/history remain
supported by tests.

Security AC1 remains a normal-mode design blocker under an untrusted local-process
threat model. Browser CSRF/Origin protections do not authenticate a local principal:
the bootstrap token is publicly readable over loopback. Local-only now disables
Codex bridge and skill mutations, including no-Origin clients with the public token,
and the UI explains the limitation. This does not authenticate all data APIs or
protect normal mode from another reachable local process.

Proposed separately scoped fix: an owner-authorized launcher delivers a one-use
capability into its browser/webview, exchanges it for a session, and requires that
session on every private read/write API. No capability on unauthenticated GET,
logs, exports or URLs retained after bootstrap; health remains minimal. Alternatively
use an owner-authenticated IPC broker. Preserve browser Host/Origin checks. Validate
unknown-capability read/write rejection, legitimate launcher restart/bootstrap and
cross-origin rejection. Persistent secrets, transport/ACL/security changes and
normal-mode migration are not activated by this candidate.

No claims of exhaustive publication/security readiness, history cleanup, real cloud
transport, inference, Jira execution, Mac acceptance or private-root migration.

Validation before checkpoint: 288 Python tests (9 platform/fixture skips), 97
headless Chrome UI tests, 11 Node report tests and JavaScript syntax checks pass.
Synthetic security/exchange focused suite: 16/16. The final UI suite includes the
security boundary changes; no real credentials were read. A small token-only
nav-tooltip foreground correction is verified by the focused theme rerun.
