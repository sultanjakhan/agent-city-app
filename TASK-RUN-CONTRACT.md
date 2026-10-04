# Task/run connection proposal

Status: the original exchange proposal below remains compatible. Local agent
access now registers actual authorized personal work through the running Cicada
authority. It does not automatically complete tasks or start human timers.

## Local agent access

`tools/agent_mcp.py` exposes independent stdio MCP servers for Cicada and Agent
City. Launch with `--app cicada|agent-city --profile <configured profile path>
--client <LocalPipeClient.exe>`. `--call <tool>` accepts one JSON argument object
from stdin for administrative diagnostics. Paths are configured host input;
tool arguments cannot select a database, execute commands or change profiles.

Both endpoints use profile-bound Windows named pipes restricted to the current
account. Other users and remote clients are excluded. This is a same-account
trust boundary; it does not isolate a malicious process running as that account.
Agent City forwards its small read/report allowlist through the existing private
host broker and one-use grants. Bootstrap, state writes and lifecycle controls
are excluded from agent requests.

Cicada `begin_ai_work` commits task/binding/report/operation receipt together.
An existing task requires its current native version; a new task is explicitly
personal. Reuse operationId and the exact request after a timeout. Changing the
payload under that ID fails. Reports use cumulative observed fields, monotonic
sequences and immutable attempt identity. Restarting a terminal attempt requires
a new run ID. Unknown model/provider/token usage stays null.

Agent City accepts the exact native binding from the selected configured source,
pairs only that explicitly reported personal task, and uses its existing RunStore.
Merely reading a cloned source does not inherit a production pairing. Report
delivery across applications is retriable, not one distributed transaction.

`tools/agent_hooks.py` handles actual local client lifecycle callbacks. It stores
only session/run IDs, native requests and receipts in a transport outbox. It
does not read or store prompt/transcript/tool arguments. Personal directory roots
are explicitly configured. One task represents a chat, with a separate run for
each observed turn. Generic chat titles are deliberate; a caller can register a
meaningful existing task with the MCP tool. Stop marks the AI turn ended, while
native task completion remains separate. An unavailable application retains the
pending item and never blocks AI work. Directory scoping is an opt-in preference,
not a data-loss prevention boundary for another process under the same account.
UserPromptSubmit reserves an attempt but does not mark it running. PreToolUse
acknowledges actual agent-loop work. A text-only turn is recorded when Stop
provides evidence it actually finished. An unacknowledged failed/cancelled
request never becomes a running task.

Local hooks require client support and trust. Cloud orchestration cannot use a
PC-local pipe; it needs a separate authenticated remote adapter. No cloud
service, publisher, public repository or paid inference is enabled here.
Native exchange/receipt stores and the transport outbox are bounded at 500
entries; capacity errors are explicit rather than silently discarding receipts.

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
