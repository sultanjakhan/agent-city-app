# Native update automation

The existing current-user-only, profile-bound AgentPipe supports these exact requests through `AgentCity.exe --agent-request-stdin <connection.json>`. These routes are dispatched by the native host, not forwarded to Python or exposed as browser HTTP endpoints. Existing request/reply framing and same-account authority apply.

- `GET /api/desktop/update-status`, body `null`: current version/source receipt, checking flag, staged version/source, last check time/reason and current idle-close deferral.
- `POST /api/desktop/update-check`, body `{}`: queue the existing signed update check/staging operation without opening a dialog. Poll status for the result. It does not close, install, change channels or accept unsigned packages.
- `POST /api/desktop/close-idle`, body `{"expectedSourceCommit":"<40 lowercase hex characters>"}`: require a staged candidate with that exact source, then inspect the current renderer and queue a graceful close only when idle is verified. A flushed acknowledgement says `closeQueued:true`; it does not claim the helper applied the update. Observe the existing installation/update receipts after process exit/restart for that result.

Unknown fields, query aliases, force/discard flags and missing expected source are rejected. Status exposes no tokens, draft text, channel paths or key material. Existing RSA verification, staging inventory, owner-process identity, backend drain, helper verification and rollback remain authoritative.

Actual application unload guards and unsent shared-task drafts block automatic close. An open dialog, in-flight fetch, changed/unavailable renderer or unresolved edit observation also defers. Native observation cannot prove a generic edited control was saved; `unverified-edits` conservatively defers until the user resolves/reloads that page. A clean hidden idle page needs no generic Yes/No confirmation. Manual close/restart confirmation remains unchanged. No route discards drafts, kills a process or focuses a window.
