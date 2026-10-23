# Owner-imported task observations

This is passive observability, separate from executor reports and task lifecycle.
Cicada remains the only task/acceptance authority. Imported metadata does not
start work, bind an executor, confirm acceptance, complete a task or touch timers.
The existing execution-authoritative contracts remain unchanged.

## Review and local import

In this source candidate's dashboard, choose a JSON file under **Imported
observations · read-only**. Review the native task identity, original SHA-256,
exporter/source, per-field evidence and unknown measurements. **Approve local
import** is a separate owner action; cancel does not write anything. This uses
the existing owner session and CSRF guard on the existing loopback server.
These routes are not in the agent MCP or one-use agent grant allowlist:

- `POST /api/observations/preview` accepts exactly `{document: <JSON text>}`.
- `POST /api/observations/import` accepts exactly `{previewToken, revision}`.

There is no new listener, service, inference, network transport or credential
setup. These are owner UI routes, not a cloud delivery interface. The frozen
installed Mac application does not implement them; see compatibility below.

Both preview and approval reread the exact selected source/profile and personal
native task through the existing read-only connector. A native executor binding,
source namespace or exchange receipt is not required. The task key in this
version is explicitly the connector's path-based key; moving the database
changes it and requires a new explicit import identity. Never infer a match from
title, directory, project, concurrent activity or a LiveSessions entry.

## Version 1 bundle (one task, one observation)

A strict UTF-8 JSON object, at most 32 KiB, with exactly:

| Field | Contract |
| --- | --- |
| `schemaVersion`, `kind` | `1`, `task-observation-bundle` |
| `observationId` | Opaque ID for one observation/measurement segment; keep it on updates |
| `sequence` | Increasing positive integer; each update is a complete cumulative snapshot |
| `task` | Exact `{profile, sourceKey, sourceId, taskKey}` from the selected personal source |
| `exporter` | `{id, source}` opaque metadata identifiers; claims supplied by the exporter |
| `observedAt`, `exportedAt` | UTC ISO timestamps ending in `Z`; observation no later than export |
| `coverage` | Explicit attempt ID, observed interval, or metadata-only snapshot; never historical thread totals |
| `fields` | Exactly the eight measured fields below, each with its own provenance |
| `skillApplications` | `null` when unknown, otherwise explicit application evidence only |

`fields` contains `status`, `sessionId`, `parentSessionId`, `model`, `inputTokens`,
`outputTokens`, `startedAt`, `endedAt`, `durationMs`. Each is
`{value, source, observedAt}`. Unknown is exactly
`{value: null, source: null, observedAt: null}`. Counters and measured milliseconds
are nonnegative integers, not estimates. IDs and provenance sources are bounded
opaque identifiers, never paths, URLs, messages or log text. Model labels are
bounded plain text. Start/end are observed event timestamps. Receipt, export,
collection and import times do not supply a missing start/end/duration.

`coverage` is exactly `{kind, attemptId, startedAt, endedAt, source}`. For
`kind: "attempt"`, supply an observed opaque `attemptId` and null interval bounds.
For `kind: "interval"`, supply null attemptId and explicit UTC observation interval
bounds. These bounds do not synthesize execution duration. For
`kind: "metadata-snapshot"`, attemptId and both bounds are null; status, token,
start/end/duration measurements and skill evidence must remain null. This permits
a known session identifier without attributing whole-thread usage to a new task.
Coverage is immutable for an observation ID. A new chat/subagent/attempt uses a
new observation ID and observed attempt/session identity with the SAME original
native task ID. An observation's counters must cover only its explicit attempt or
interval, never historical session/thread totals. Supplied scope claims remain
unverified exporter provenance.

`status` is an explicitly observed execution state, or unknown. Only fresh
running/waiting evidence (within five minutes of that field's observation time),
explicit coverage and an open native task can appear in **Current**. Metadata-only
snapshots, planned tasks without such evidence, stale/ended attempts and completed
native tasks appear only in imported **History**. The import timestamp cannot
refresh runtime state. Ending a chat/attempt does not complete its native task.
Imported rows are separate from LiveSessions and authoritative local reports.
The automatic create/reuse-task workflow is deferred; no native-write tool or
bridge is added by this pilot.

Each skill evidence item is exactly
`{skillId, evidenceId, source, observedAt, kind: "applied"}`. The producer must
have an explicit application event. A skill read, inventory entry or availability
is not an application. `null` means unknown, `[]` explicitly reports none.
Per-field provenance and application claims are **not independently verified
execution evidence**. Owner approval authorizes a local metadata import only.
Prompts, messages, hidden reasoning, tool arguments/results, credentials, raw
logs, unrelated tasks and arbitrary additional fields are rejected.

## Persistence and projection

Only `imported-observations.json` under the existing external panel directory is
written. It preserves exact original JSON text, its SHA-256 and import timestamp
for each accepted version. The latest version appears once in a separate
`importedObservations` dashboard section, alongside its original native task ID,
field provenance and preserved receipt hashes. Local/executor `runs`, activity
state, timers and token totals are not merged with imported observations.

Exact historical replay is a no-op and cannot roll back the latest version.
Different content at the same/older sequence, changed task/exporter/session or
known model/time identity, decreasing counters, regressed observation times or
removed/changed application evidence conflict. Unknown fields may become known.
At most 100 receipts/2 MiB are retained; capacity fails explicitly without
pruning original hashes. Ten review previews, each expiring after ten minutes,
are bounded in memory. Preview tokens and file revision are checked on approval;
source/task/personal scope are checked again. Reopening validates stored original
bytes against their hashes. Redirected storage paths fail closed. A source/task
that is no longer selected or personal is hidden as unavailable, not rebound.

## Cloud evidence and real pilot gaps

`tests/test_observation_import.py` uses a real temporary Store, SQLite connector,
owner HTTP bootstrap/import, dashboard API and Store reopening. Its existing
personal task has no timer or executor binding. Tests prohibit calling native
binding authorization, RunStore.report or WorkExchange.apply during observation
import. Source task/timer files stay byte-identical. Fixtures are synthetic. `node --test tests/observation-current.cjs` also checks
the actual Current classifier without requiring a browser.
`tests/observations.spec.cjs` separately tests the review UI with explicitly
synthetic presentation API fixtures; it is not native/import integration proof.

A bounded allowlisted probe of this cloud runtime exposed a session ID through
`CODEX_SESSION_ID` (also `CODEX_THREAD_ID`). It exposed no turn ID, turn start/end,
input/output token counters or applied-skill event. No private config, journals,
transcripts, credentials or unrelated paths were read. The private runtime pilot
bundle explicitly declares metadata-snapshot coverage and contains only that
observed session ID, collection/export timestamp and
the task identity supplied by the coordinator; other measurements/evidence stay
null. Collection time is not turn start. The coordinator's delegation thread ID
is not asserted as a measured parent session. Task existence/scope must still be
validated by the installed read-only connector during any eventual import.
Full real-token/time/skill telemetry acceptance therefore remains blocked on an
actual instrumented metadata source. No runtime pilot identifiers are published
in this repository or its PR.

## Frozen Mac 0.5.26 compatibility package

The public repository candidate is not the frozen passive Mac runtime. Its
LiveSessions collector, GET-only handler and foreign WIP must not be replaced
with this repository's full-service server. No Mac process, build, model, server
or service is run by this work. No installation or real import is claimed.

This PR is the reviewable source package: `observation_store.py`, the narrow
`CicadaConnector.read_observation_task` addition, Store projection/owner-route
changes in `server.py`, `static/observations.js`, and the small HTML/dashboard
hooks, with synthetic tests. The executor reporting modules are not observation
import adapters. The standalone schema/validator and display can be reused after
review; do not copy this server over the installed GET-only server.

To prepare an exact compatible patch, the minimal **read-only source inputs**
needed from the frozen build are:

1. Its server entry module containing Store initialization, dashboard GET
   projection and blanket POST-405 handling, plus its existing storage lock/
   atomic-write and owner-approval mechanism (if separate modules).
2. Its read-only Cicada connector module: selected profile/source identity,
   exact-task lookup and personal-scope conventions.
3. Its LiveSessions collector module and the function that maps collector
   records into dashboard/session rows; preserve its fields and local provenance.
4. Its dashboard template and JS renderer (and any required shared DOM helper)
   at their actual installed revision. A CSS excerpt is needed only if these
   existing card/dialog classes are absent.

No production database, journal, credentials or private config is needed for
that source review. The compatible first-import design must retain all POST405:
use an explicitly owner-approved offline/local import mechanism already allowed
by that runtime, if one exists, followed only by lightweight GET readback. If
none exists, a separately reviewed offline import capability is required; this
candidate does not silently enable one. Mac verification remains: exact native
personal identity, imported/read-only label and provenance, null gaps, replay and
restart readback, and unchanged task/timer data. LiveSessions and imported rows
must remain distinct; session/task links require explicit supplied identity.

### Current cloud check limits

Backend integration and the actual Current classifier can run in this cloud
image. The focused Playwright UI cases could not launch because Chromium's
executable is absent. The official cloud command
`node <runtime>/playwright/cli.js install chromium` was attempted; the environment
rejected network access to `https://cdn.playwright.dev:443` by policy. Browser
behavior/visual acceptance remains unverified. Syntax and Node classifier tests
are separate evidence, not a browser pass. No Mac/PC fallback was attempted.
