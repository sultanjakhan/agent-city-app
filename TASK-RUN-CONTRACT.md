# Task/run connection proposal

Status: proposal for coordination before Cicada integration. No Cicada writes,
ID migration, reporting protocol change or automatic task completion is included
in the connection-status release.

## Existing compatible report contract

Use `city.py dashboard` to obtain a task key, then
`city.py report-run --file <local-report.json>` to report actual authorized work.
The accepted schema is defined by `public_api.reporting()` and `run_store.py`.

| Field | Meaning |
| --- | --- |
| `runId` | Unique opaque ID per execution attempt; a UUID fits the existing validator. A retry or different executor gets a new ID. |
| `sequence` | Increasing integer from 1; each message is a complete cumulative snapshot. Repeating an identical sequence is idempotent; older or different same-sequence messages conflict. |
| `taskKey` | Exact dashboard key for an explicitly matched Cicada task, otherwise `null`. Never guess from a title. |
| `agent`, `provider`, `model` | Observed executor identity; unobserved provider/model are `null`. Identity and task cannot change within a run. |
| `stage`, `status` | Technical execution stage and `running`, `waiting`, `done`, `error`, or `cancelled`. They do not change Cicada task completion. |
| `skillIds` | IDs of skills actually used, not installed or available skills. |
| `inputTokens`, `outputTokens` | Observed cumulative counters, otherwise `null`; reported counters cannot decrease. |
| `mcpCalls` | `null` when unknown, otherwise cumulative `{server, tool, calls}` counters. No arguments or results. |

Server timestamps `firstReportedAt` / `updatedAt` mean receipt time, not measured
execution duration. Dashboard telemetry is explicitly `reported`; it must not
be presented as independently verified. Catalogue membership or client presence
cannot produce execution events or counters. Reports exclude task text, notes,
prompts, credentials and tool arguments/results.

## Stable cross-application identity: decision needed

Current task keys are `cicada-<16-char hash of database path>-<sourceId>`.
This separates the currently configured databases, but relocating a database
changes the key. Do not duplicate this path-based identity in Cicada.

For future integration, agree on a persistent, opaque `sourceNamespace` stored
with the Cicada source (distinct for production and development), plus its
existing immutable item `sourceId`. The pair is the task identity; all retries
use that pair and distinct run IDs. A moved database retains its namespace;
an independent clone must explicitly receive another namespace. Define how
legacy path-based keys bind to the stable identity before migration. Do not
derive task identity from a title, account name or filesystem path.

## Optional factual telemetry extension: not implemented

If executor instrumentation provides it, a future version can add
`observedAt`, `telemetrySource` (e.g. executor event stream or usage receipt),
and measured `durationMs` / technical tool counters. Values remain `null` when
unobserved. Do not add these fields to today's strict endpoint: it rejects
unsupported fields. Version and validate the extension jointly before sending
it. A run can finish while its Cicada task still requires review or acceptance.
