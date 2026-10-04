# Configurable native task integration

Cicada owns explicitly shared personal tasks in its existing SQLite `items`
table. Agent City owns a confirmed projection, durable command outbox and
connection settings, never a competing task authority. Existing tasks are
shared by exact native ID and revision. Titles do not identify tasks.

## Contract and application adapters

The version-1 command envelope is `{version:1, operationId, command, arguments}`.
The native Cicada pipe adapts it to `{version:1, operation_id, action:"task-command",
body:{command,arguments}}`. Cicada's own UI uses `shared_task_command` with the
same three fields inside `input`. Agent City's queue accepts the wire envelope.
One operation ID always refers to one immutable command payload.

| Command | Arguments | Scope |
| --- | --- | --- |
| snapshot | `{}` | tasks:read |
| get | taskId | tasks:read |
| operation | operationId | tasks:read |
| create | title, content | tasks:write |
| share | taskId, expectedVersion | tasks:write |
| patch | taskId, expectedVersion, patch | tasks:write |
| comment | taskId, expectedVersion, comment | tasks:write |
| submit_result | taskId, expectedVersion, runId, content | tasks:execute |
| review | taskId, expectedVersion, resultVersion, decision; comment for rework | tasks:review |
| acknowledge | taskId, expectedVersion, intentId, report | tasks:execute |
| archive | taskId, expectedVersion | tasks:write |

Patch fields are title, content, stage, process, waiting and status (`task`/`done`).
Required fields are exact; unknown fields are rejected. Status changes for tasks
with a reviewed-result lifecycle must use review commands. Active human timers
prevent acceptance/completion. Generic SQL/UI completion cannot bypass an
unaccepted shared result. Timers are never started by task commands.

Bindings contain sourceNamespace (persisted UUID), sourceType `note`, sourceId
(native ID), taskKey (`cicada-` + first 16 SHA256 namespace hex digits + `-` + ID).
Namespaces survive moving a database. Independent cloned authorities need an
explicit separate namespace/profile; do not point writers at divergent clones.
Existing descriptions, tag-based stage history and workflow state remain in place.
Immutable results and review records reuse existing native review tables.

## Connection setup

In Settings → Connectors → Shared tasks, choose an endpoint or a local pipe
profile/client, select scopes, optionally restrict exact task IDs, and test the
exchange. Source namespace pins after the first confirmed exchange. The screen
shows the last successful exchange and a safe, actionable failure category.
Changing an existing populated source requires a separate Agent City data profile;
queued edits and confirmed data are never discarded automatically.

Local pipes authenticate the current OS account and reject remote clients.
Profile/client paths are configuration, not hardcoded deployment assumptions.
The optional stateless HTTP gateway authenticates scoped bearer grants and
forwards commands to the native app; it does not store tasks. Bind loopback by
default; remote binding requires explicit TLS certificate/key configuration.
Non-loopback HTTP clients require HTTPS. Redirects and URL credentials are denied.

Create an independent backend connection JSON using the fields returned by
`task_connection.default_config()`: enabled, transport, endpoint, profile, client,
tokenEnv, sourceNamespace, scopes, taskIds, staleAfterSeconds. For `pipe`, endpoint
and tokenEnv must be empty; profile/client must be absolute. For `http`, profile
and client must be empty and tokenEnv names an environment variable available
to the background process. Never place the secret value in this JSON or UI.

Gateway grants are an array of `{tokenEnv, scopes, taskIds, sourceNamespace}`.
The service process receives each bearer secret via the named environment
variable. Use at least 32 URL-safe random characters. Provision/revoke secrets
using the deployment's existing protected credential mechanism. No credentials,
service startup entries or remote deployments are provisioned by these sources.

Run independently for each app:

```
python tools/task_gateway.py --app cicada --backend <connection.json> --grants <grants.json> --port <port>
python tools/task_gateway.py --app agent-city --backend <connection.json> --grants <grants.json> --port <other-port>
python tools/shared_task_mcp.py --connection <independent-client-connection.json>
```

Agent City's API adapter enqueues mutations and returns pending acknowledgement,
not native completion. Its snapshot contains confirmed projection and exchange
freshness. Use its existing local MCP tools for queue/exchange/conflict access.
Cicada command access returns native transaction receipts. MCP alone does not
sync data: `TaskSync` explicitly drains the queue then refreshes a complete
snapshot in the existing background service. Both apps work with exchange disabled.

## Results, retries and conflicts

`submit_result` requires an observed completed run bound to the exact task.
Execution completion leaves the result awaiting review. Acceptance retains all
results/history and moves the task to history. Rework retains the result and
feedback, creates exactly one awaiting-dispatch intent, and changes to running
only after the executor acknowledges that intent with a new run ID and running
sequence-1 report. The caller must be performing authorized work; commands do
not launch a model. Existing begin/report commands remain separate telemetry.

Task rows use expectedVersion; review also uses resultVersion; execution reports
use per-run sequence numbers. Conflicts return current authorized projection and
remain visible alongside the immutable draft. Explicit reconciliation retires
the old draft into history, then uses a new operation ID and current revision.
Retry an unknown outcome with exactly the original operation ID and body.
Native receipts and Agent City queue/ACK/projection commit atomically. UI drafts
persist before transmission; transport failures retain them. Complete snapshots
and archive tombstones avoid silent projection truncation. Capacity limits fail
explicitly (500 bindings/pending commands, 5,000 receipts, 900 KB native snapshot,
16 MB projection/outbox document); no implicit pruning or history deletion.

The latest executor report, executor/model when reported, report receipt time,
exchange time and staleness are distinct. Earlier reports have unknown receipt
time; requests and missing model metadata never imply running or a guessed model.

## Acceptance commands

Build Cicada's native test harness first, then set `CICADA_NATIVE_TEST_EXE` to its
freshly compiled library test executable. Run:

```
python -m unittest discover -s tests -p test_task_sync.py -v
npx playwright test tests/shared-tasks.spec.cjs
```

The cross-app suite uses actual native SQLite code, temporary databases, durable
Agent City storage and a real authenticated loopback gateway. UI tests use
synthetic API fixtures and headless Chromium. Neither proves installed native
visual acceptance; report source/build/runtime/installation separately.
