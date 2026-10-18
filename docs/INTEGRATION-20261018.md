# Combined Agent City fixes

Base: `d3aafd700e4b832f415a18311431d1c75453d8e3`.

The source now keeps missing reported models explicit, distinguishes source
readability from successful task/report exchange, migrates a nested panel without
copying its own held writer lock, and filters Current/History by project and tag.
Executor completion does not imply user acceptance. Fresh work on a completed
native task remains in Current. Native and run IDs remain exact.

## Source provenance

Bundle: 101131 UTF-8 bytes, SHA256
`6b3dd1c384407f92e8616bcc388ac691a59dd0a7d2fa16b9bb09791e8ee7e360`.

| Candidate | Original source commit | Original patch SHA256 |
| --- | --- | --- |
| Actual model | `79c81ec7ecb11045953afe2dada5b318004737c2` | `847dfe687b400c14b0b30c6de30d7a9f9d98da8be05893186a61ae12c0d1d327` |
| Integration states | `a51917f2ba17329b4255c2f41ccc724a7f6b89ae` | `1f81f6159e9da87d73cc03a8b3899e94090f590be72a3bf696e759a115d822f9` |
| Migration lock | `2f34f03e7b33a2419c726920f77a12b2dd175f91` | `42cdee15a2e8ae15916e36c3dcd3bac11dce59fbd320fb9adebec1595e6ac11e` |
| Dashboard filters | `361bc3bde4efe6135d6af8f6e8851e9b7c11f137` | `fe63da221da02d6e8357456a6ef3b9f6995dbd8c199355c4f129a34a954f9f9e` |

Patch strings in the bundle use LF; the manifest hashes and sizes describe CRLF.
All four hashes were verified with those original line endings before application.
The integrations export repeats the exact actual-model hunks and regression test;
those were verified identical and included once. Both candidates insert English
translations at the same anchor; all translations are retained. Source changes
were reconciled in the owned Linux cloud checkout, without importing private Git
history, original workstation paths or user data.

## Validation and delivery boundary

The affected connector, dashboard HTTP and migration suites pass (35 tests), as do
17 model/integration/projection Node tests and JavaScript syntax checks. Four build
preparation tests check refusal on Linux, refusal to reuse an existing directory,
corrupt wheel refusal, and locked offline installation command construction.
They do not claim a Windows build.

The broader Python run before adding preparation tests ran 361 tests: 344 passed,
13 skipped, 3 failures and 1 error. Each failing test reproduces on the unchanged
base in the same Linux environment (Windows launch/native client assumptions and
the existing skill symlink check). The broader Node run has two scripts blocked
by missing jsdom. Chromium installation was blocked by cloud network policy;
Playwright browser and native Windows acceptance remain unverified.

The separation scanner reports only the existing public `desktop/AgentCity.ico`
as an unreviewed binary. It is byte-identical to the base; this integration adds
no binary, credentials, profile, database or private source history.

The **Windows cloud QA candidate** workflow (pull requests and manual dispatch) prepares the checked-in wheel
hashes and locked NuGet dependency, calls `tools/build_desktop.py` from an exact
clean commit, and runs host/backend self-tests. Its one-day artifact is unsigned
QA output, not a supported update. Pull-request runs check out the exact head SHA and bind the build receipt and
artifact name to it. Manual dispatch is also available after default-branch integration.
It provisions no service and reads no signing secret.

For a supported update, follow `WINDOWS-UPDATES.md`: select the approved newer
application version, build clean source, then run `New-AgentCityUpdate.ps1` under
the existing maintainer Windows identity with its existing DPAPI-bound key. Publish
the ZIP, signed `latest.json` and signature together. The integrated source initially retained version 0.5.24. The separate release
preparation aligns application, UI and native metadata at 0.5.26: pending 0.5.25
candidates and the draft 0.6.0 reservation are preserved. This remains unsigned
QA preparation; no release is published and no installed application is updated.
The supported updater must wait for normal owner closure and backend drain; no
active device, foreign process or draft is closed by this work.
