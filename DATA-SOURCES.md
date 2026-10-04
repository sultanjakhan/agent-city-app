# Data sources (0.5.17)

Settings > Data and sources supports two optional private folder bindings.
Preview reads allowlisted summaries only (counts, file timestamps and states).
Apply saves the local view configuration; it never changes the active runtime,
skills directory, authentication, calendar database or task identity.

The local profile is `data-sources.local.json` in the configured panel directory.
Absolute paths stay there. Portable export contains no local bindings. Export
is a bundle with schemaVersion 1, appId agent-city and profiles. Each profile
contains id, repositoryKind and config. The per-profile config uses the agreed
shape: schemaVersion, appId, source {kind: directory, path: null},
structureVersion, localGit: false, sections {id, visible, placement, order},
refresh {mode: manual}, onboarding {status: skipped}. The bundle wrapper is
Agent City's extension; native Cicada config is not imported as if equivalent.
Cicada's own section IDs/placement require an explicit adapter before integration.
Import validates a draft; a separate preview and Apply are required to save.

Agent City summary layout: panel/projects.json, panel/agent-runs.json and skills.
Cicada summary layout: profiles/production/calendar.db and profiles/dev/calendar.db.
These Cicada paths are a proposed private scaffold, not an active database
migration or a claim about the producer's current layout. A missing file is
shown as missing. Databases with a WAL are shown as busy without opening them.

Creating structure requires a matching preview and separate confirmation.
Only empty, known directories are created. Existing files are preserved. No
Git initialization, remote, push, data copy or database creation is performed.
Git commands shown in Settings are instructions the user may run manually.

Paths reject network roots, traversal, protected components, code locations and
observed symlink/reparse ancestors. This validation is not a complete defense
against concurrent filesystem replacement (TOCTOU). Preview expires and is
bound to the current configuration revision. Conflicting writes preserve the
draft and require another preview. Export/import rejects unknown fields.

A genuinely empty profile with no saved source configuration offers setup or
Skip. Skip stores an empty binding configuration. Existing runtime profiles
are not reset or forced through onboarding. Dashboard summaries appear only
for saved sections explicitly placed there.

Work-registry and task-run exchange are separate next integrations. Source
folder IDs are not task namespaces. No executor permissions or paid inference
are granted by this screen.

Raw portable file imports are limited to 16 KiB and depth 16, decoded with
strict UTF-8, and reject duplicate JSON keys and nonfinite numbers before
schema validation. Existing saved local profiles are not rewritten by this
change. Browser confirmation is a user interaction, not authentication of a
local caller that can form HTTP requests.
