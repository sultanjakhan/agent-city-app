# Agent City 0.6.0 candidate

## Source and behavior

The candidate builds on PR #9 (`4052ebf20908a91f05c1ad8152ca22eadfceedf6`),
which contains the pending 0.5.25 task transport and native draft lifecycle fixes.
It changes the web workspace and application version to 0.6.0. It does not
migrate task ownership or replace existing private data and credentials.

Dashboard shows current observed work. Tasks joins Cicada records, shared-task
records and run reports by their source namespace and stable task ID. Project
labels from the work registry require a confirmed binding. Completed Cicada tasks
without stored run reports are outside the current history API; this candidate
does not claim to list Cicada's entire archive.

An open task uses one main content area. Overview, History and Context are local
tabs; selecting an observed stage shows its actual reports below the selector.
Unknown usage remains unknown, stale reports do not imply active execution, and
creation does not start an executor. Existing shared-task review commands preserve
result versions and the expected task version.

Architecture contains process configuration, shared standards and storage
locations. A saved process does not execute. Standards are proposals; the neutral
design version remains a draft and exact component geometry is not approved.

## New owner API

All endpoints require the existing owner session. The write endpoint also
requires the application CSRF token. Existing agent delegation scopes are unchanged.

| Endpoint | Result |
| --- | --- |
| `GET /api/standards` | Shared version summaries and catalog revision |
| `GET /api/standards/detail?id=…&version=…` | Exact original, rules and provenance |
| `GET /api/standards/assignments?repoId=…` | Exact project references and revision |
| `POST /api/standards/apply` | Assign `{repoId,id,version,revision}`; stale revision returns 409 |
| `GET /api/hardware` | OS, CPU count, available memory facts and data-disk capacity |
| `GET /api/storage-map` | Actual owner and path metadata; no file contents or keys |

`GET /api/v1/context?cwd=…` adds `standards`, containing the exact assigned
originals for the matched repository. Standards do not override repository rules,
grant permissions, execute QA or apply a stylesheet.

`standards-catalog.json` stores originals in the private panel data directory.
`standard-assignments.json` stores repository ID and version references. Neither
file is written into a project. An original's content hash is validated; repeat
assignment is idempotent and malformed requests do not change the saved files.

## Verification and publication boundary

The candidate has syntax, Python store/HTTP and Node regression checks, plus
browser checks against a synthetic loopback fixture. Browser acceptance covers
1100 px and 390 px, local task tabs, stage selection, process persistence and
project-to-standard selection. These checks do not validate a Windows binary.

On macOS, the full Python suite ran 385 checks: 360 passed, 14 skipped, and
11 failed or errored. The same 11 outcomes were reproduced on the clean PR #9
baseline: Homebrew Python symlink setup restrictions, missing Tk, Windows-specific
native tests, and a pre-existing skill-symlink test expectation. No new Python
failure was introduced in the checked suite. The existing two DOM test scripts
require an unavailable `jsdom` dependency and were not run. Adapted Playwright
specifications were not executed; browser evidence comes from the CUA fixture.

Stable publication requires the Windows x64 candidate, native acceptance, and
three assets: the Windows ZIP, `latest.json`, and `latest.json.sig`. Build an exact
clean source commit with `tools/build_desktop.py` using the documented offline
dependency directory. Sign with `tools/New-AgentCityUpdate.ps1` under the existing
maintainer Windows account. The DPAPI signing key must remain outside Git and
must match `desktop/UpdateTrust.cs`. See `WINDOWS-UPDATES.md`.

Do not publish a source-only candidate as a working stable application update.
