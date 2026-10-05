# Local API and MCP client setup

This source supports opt-in Windows MCP connections for **both** Cicada and
Agent City. Cicada owns personal task UUIDs, revisions and results; Agent City
owns execution telemetry and its confirmed task projection. MCP invokes the
application APIs. The independent TaskSync outbox performs synchronization.
Neither MCP registration nor a hook starts a model or a human task timer.

These adapters must be included in the applications you install. A public
release that omits them cannot provide the local pipe APIs even if a client
configuration exists. Check source/release provenance, rather than treating a
local candidate as published software.

## Prerequisites

Use Python 3.11 or newer, .NET 10, and installed API-enabled versions of both
applications. Build the public native helper from this repository:

```powershell
dotnet publish tools/pipe-client/LocalPipeClient.csproj -c Release -o <client-output>
```

Select existing private Cicada and Agent City profiles. Place transport files in
a separate private user directory outside this repository and both app data
directories. Profiles, private roots and client homes are parameters; no author's
username, task IDs or production paths are built into setup.

## Plan, then apply

```powershell
python tools/configure_agent_clients.py `
  --tools-dir "<private transport directory>" `
  --native-client "<client-output>/LocalPipeClient.exe" `
  --cicada-profile "<existing Cicada profile directory>" `
  --city-profile "<existing Agent City connection.json>" `
  --client codex --client claude
```

The first run prints a plan and writes nothing. Repeat with `--apply` to copy the
MCP/hook scripts and complete native helper, and merge only the two selected MCP
entries into user client configuration. Codex uses `CODEX_HOME` when configured;
otherwise its usual user directory. `--codex-home`, `--user-home` and `--python`
permit explicit paths. Claude Code uses the selected user's `.claude.json`.
Existing unrelated settings, MCP servers and hooks remain present. Different
existing configuration under either integration name stops setup before writes.

Add `--hooks --personal-root "<explicit personal project directory>"` for
automatic observed lifecycle reports. Repeat the root option as needed. These
hooks report identifiers and observed metadata; prompts, transcripts and tool
arguments are not stored. Client hook trust is still the user's choice; this
script does not change trust or approval policy. The generated Windows shell
command supports Unicode, spaces, apostrophes and dollar signs in paths.

Repeating the same setup creates no duplicate entries or new backup. Changed
files have a private backup with a manifest in `setup-backups/`. Concurrent
configuration changes stop the write instead of overwriting the changed file.
If setup stops after some writes, inspect that manifest: rollback is prepared,
not represented as an automatically verified recovery.

Restart/reconnect the selected client to load new MCP definitions. Client setup
does not launch applications or configure their synchronization, cloud access,
credentials, automatic approvals or other AI clients.

## One-time task exchange setup

In Agent City's owner settings, select Connectors → Shared tasks, select the
Windows pipe transport, supply your Cicada profile and copied native helper,
choose intended scopes and task restrictions, then save/test. The authenticated
owner configuration gate remains intact. A native or MCP task command cannot
silently grant itself connection access.

## Portability and publication limits

The setup and native helper currently target Windows. A Mac/Linux transport or
cloud AI lifecycle adapter requires its own implementation and acceptance.
Local MCP configuration is distinct from a plugin package or public plugin
catalog submission. Publishing source does not register a catalog plugin, and
sharing source never shares an author's private application data or keys.
