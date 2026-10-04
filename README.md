# Agent City

Local application for agent activity, model catalogues, projects and skills.
Python 3.11 or newer is required. Core features use the Python standard library.

## Windows desktop

The Windows desktop host uses a branded icon, one window per profile and a
stable executable path. Repeated launches show the existing window. Signed
updates are checked in the background and installed after the app closes;
receiving public updates requires no GitHub account or CLI.

Releases are published at
[GitHub Releases](https://github.com/sultanjakhan/agent-city-app/releases).
The first release contains the signed update package for an existing native
installation. It is not a universal first-install wizard: .NET 10 Desktop Runtime
and WebView2 are prerequisites, and first installation on another computer
has not been accepted yet. See [Windows updates](WINDOWS-UPDATES.md) for the
channel and maintainer instructions, and [source provenance](SOURCE-PROVENANCE.md)
for the first release's build identity.

## Run

From this directory, run `python launch.py`. On Windows, `Start-AgentCity.cmd`
opens the application. For an offline first check, run
`python server.py --no-refresh --port 47839` and open `http://127.0.0.1:47839`.
Optional cloud dependencies are listed in `requirements-cloud.txt`.

`python launch.py --local-only --no-refresh` keeps local data editing available
while disabling cloud profile access/sync, credential observation/mutations and
provider/network checks. The UI displays this mode. Existing secrets and profiles
remain untouched; enabling those integrations later is a separate choice.

## Separate private storage

The existing encrypted activity relay is included in [sync-relay](sync-relay/README.md).
It uses Cloudflare SQLite Durable Objects compatible with Workers Free and keeps
Agent City independent of Cicada's data and keys. This currently covers activity
reports, not a complete settings/skills synchronization system.

Application source and synthetic demonstrations live in this repository. Mutable
projects, skills, rules, settings and activity live outside it. A new installation
defaults to the adjacent `../agent-city-data/` directory. On first use it receives
a synthetic example skill; real projects take precedence over the demo seed.

Copy `storage.example.json` to ignored `storage.local.json`, or set
`AGENT_CITY_CONFIG` to a private JSON pointer. Relative paths are resolved against
the pointer's directory, so the app/data pair can move together. Alternatively,
set `AGENT_CITY_DATA_ROOT`. `AGENT_CITY_PANEL_DATA`, `AGENT_CITY_SKILLS_ROOT`,
`AGENT_CITY_CREDENTIALS_DIR` and `CODEX_HOME` override individual directories.

The private directory contains `panel/`, `skills/`, `credentials/`, `codex-home/`
and `repositories/`. Defaults scan only the configured private skill/repository
roots. Configure external repositories and Cicada database paths in the private
pointer. Optional read-only installed skill locations can be listed with
`skillInventoryRoots` entries containing `origin` and `path`. Installed-agent
skills and production databases are not discovered
automatically. Codex global configuration is touched only by an explicit UI action
against the configured Codex home.

Saved provider keys use Windows DPAPI in the configured external credential
directory; environment variables remain supported. Credentials do not belong in
either Git export. Existing keys may remain in their original OS-bound location
and be referenced by the private pointer. Never publish the private pointer.

## Checks

Run `python -m unittest discover -s tests`, `npm run check` and, after installing
the development dependencies, `npm run test:ui`. The separation acceptance check
is `python tools/verify_separation.py`; it uses temporary synthetic data and an
ephemeral local HTTP port, without starting provider refreshes.

The project is licensed under [MIT](LICENSE). Bundled third-party code and
dependencies retain their own license notices. Private data, credentials,
signing keys and development history are excluded from this repository.

## Connection observations (0.5.15)

Connection cards show catalogue provenance and its saved date separately from
account access. Details show the last refresh attempt and classified failure,
current local-only pause, and dated prior observations. A public catalogue,
stored key, or previous client sign-in never implies current authentication,
model entitlement, inference success, or provider-wide availability. Error
messages in these details are allowlisted categories, not raw source text.

The existing task/run reporting contract and a proposed stable source identity
are described in [TASK-RUN-CONTRACT.md](TASK-RUN-CONTRACT.md). This proposal does
not change Cicada or migrate existing IDs.
