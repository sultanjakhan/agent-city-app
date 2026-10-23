# Frozen passive LiveSessions exact-turn adapter

This compatibility package is independent of the public full-service import UI.
Do not copy the public `server.py` over the frozen installed server. Keep the
supplied `passive_server.py` constructor, verified ProductionBinding, existing
GET allowlist, every POST405, readOnly=true, discovery=false and cloud=false.
No daemon, endpoint, writer, journal scan, credential enrollment or native task
mutation is introduced. These modules have not been installed or accepted on Mac.

## Two small drop-in modules

- `passive_attempts.py`: standard-library-only read wrapper around the existing
  `LiveSessions.snapshot()`. It reads at most 16 KiB from the single explicitly
  owner-authored `passive-attempt-binding.json` in the existing panel directory.
  It never creates or edits this file or a database.
- `static/passive-attempt-view.js`: optional small formatting helper for the
  supplied incremental renderer. It does not replace the DOM updater, polling,
  routing, disclosures, collector or server.

The wrapper rereads its file and the connector on every projection. It calls
`snapshot(task_keys=[the exact connector task key])`, requires connected source,
exact profile and sourceKey, exact original sourceId and connector taskKey, and
personal scope tags. It keeps an optional independently supplied native taskKey
separately: namespace-based and path-hash keys are never inferred equivalent.
A title/UUID alone is not a binding. If tags/personal scope are unavailable, the
exact session/turn is absent/duplicated, or any source identity changes, it leaves
the collector snapshot unlinked and returns a bounded unavailable diagnostic.

Only the approved session row is projected. Its stages contain exactly the
approved observed turn ID. Only that turn's explicit usage counters and model
are copied; absent values stay null. Whole-thread totals, session model, past
turns, result text, task text, action summaries and unknown metric aliases are
not copied into the bound row. Only host-confirmed project/agent/parent identity
keys may be retained for existing routing. Unrelated sessions remain unchanged.
The original collector snapshot is not mutated. Directory-level collector
summaries remain collector data; they must not be interpreted as draft usage.

Original turn events and skill-read inventory names are not treated as applied
skills. The only application events injected into the bounded turn come from
explicit `appliedSkills` records with matching turnId and fixed
`source: "executor-reported"`, labelled **executor reported**, never independently
verified. Null means unknown, an explicit empty list means none reported. A
reported event outside known turn bounds is rejected. No prompts, hidden
reasoning, messages, tool arguments, credentials or raw journals are read.

## Owner-authored binding schema

Strict JSON with exactly:

```
schemaVersion: 1
kind: passive-attempt-binding
bindingId: opaque owner approval identity
sessionId: exact observed root session identity
turnId: exact observed CURRENT turn identity
approvedAt: owner approval UTC timestamp ending in Z
task: {profile, sourceKey, sourceId, taskKey}
nativeTaskKey: independently supplied native key, or null
appliedSkills: null or [{id, turnId, skill, at, kind: applied, source: executor-reported}]
```

All identifiers, labels, times and list sizes are bounded and validated; unknown
fields, duplicates and redirected binding paths fail closed. Runtime/pilot task
IDs, actual sessions and approvals do not belong in public source or fixtures.
The owner/coordinator supplies this one file through its existing permitted
local-file workflow. This package supplies no HTTP writer or automatic task
creation/reuse. Changing the file is a new explicit owner choice, not inferred
attribution. A generated bindingId is a document identity, not an observed turn.

The previously exported worker metadata snapshot is NOT a root-chat turn binding.
An actual current root turn ID and collector mapping are still needed; do not
substitute a whole-thread ID, create a random turn ID or borrow past thread totals.

## Narrow integration into the supplied passive entry point

Immediately after its existing `store.live_sessions = LiveSessions(...)` line,
the reviewed host can wrap that same collector:

```python
from passive_attempts import BoundLiveSessions
store.live_sessions = BoundLiveSessions(
    store.live_sessions, store.cicada, Path(value['dataDir']),
    sessions_path=HOST_VERIFIED_SESSION_LIST_PATH,
    identity_fields=HOST_VERIFIED_ROUTING_ID_KEYS,
)
```

These two constants MUST come from the actual collector interface, not a guessed
schema. For example, tests explicitly use `('sessions',)` and
`('projectId', 'agentId')`; they are synthetic interface fixtures, not evidence of
the installed path. No changes to Store construction, binding.verify(), server
startup, health flags or GET/POST policy are needed. The wrapper deliberately
omits unknown metric aliases instead of risking historical thread attribution.

The existing `item.task` TEXT field receives the original native task title plus
all four connector identity fields, optional native key, bounded turn ID and
explicit unverified provenance. `item.name` shows that same task title. Session,
turn and routing identities remain distinct. It never changes Cicada completion
or timers. A stopped/completed attempt does not complete its task.

## Tiny conditional renderer splice

Load `passive-attempt-view.js` before the actual LiveSessions renderer through
its existing static asset loading mechanism. In the supplied `updateStageNode`,
replace only the `.ls-stage-metrics` assignment with this conditional; preserve
the original calculation for unrelated/unbound stages:

```javascript
const scopedMetrics = globalThis.PassiveAttemptView.stageMetrics(
  stage, formatNumber, formatDuration
);
summary.querySelector('.ls-stage-metrics').textContent = scopedMetrics !== null
  ? scopedMetrics
  : `${formatNumber(stage.usage?.total)} tokens · ${formatDuration(stageDuration)}`;
```

Bound stages with a reported duration show **collector-reported duration**. A running turn
with an observed start and no end may show **running elapsed · derived from
observed start; not completed duration**. Ended turns with no measured duration
show **duration unknown** even if start/end exist. Receipt/import time is never
used. Unknown total tokens remain **Unknown**, not zero or a sum of inferred
fields. The task summary and skill labels also keep claim provenance visible.
The existing incremental patchList/disclosure logic is unchanged.

## Exact remaining source inputs

The supplied excerpts are enough for this tested projector but not an honest
claim of final installed wiring. Provide only these small interfaces from the
frozen source, not private data or logs:

1. `LiveSessions.snapshot()` return assembly and one synthetic/session schema:
   exact session-list path plus the project/agent/parent identity fields consumed
   by directory/session routing.
2. The renderer's `patchMetrics(item)` function, so its exact metric field reads
   can be checked against the deliberately scoped row. Missing fields must render
   unknown and must not fall back to previous session/global data.
3. The actual LiveSessions JS filename and its template script-loading line (and
   static GET asset mapping if it is an explicit allowlist).
4. If the verified connector omits `tags`, its existing read-only personal-scope
   representation or exact-task projection function. No native write API is needed.

The coordinator must also select the actual current root turn ID via its allowed
read-only metadata view. No real root binding is fabricated by these cloud tests.

## Cloud evidence and CI diagnosis

`test_passive_attempts.py` uses a synthetic collector plus the actual read-only
SQLite CicadaConnector with one temporary personal task and no timer. It checks
exact turn scope, no thread-model/totals leakage, unrelated-session preservation,
explicit reported skill events, fresh identity/personal-scope revalidation and
byte-identical task/timer files. `tests/passive-attempt-view.cjs` tests the actual
formatting helper. These are synthetic module/integration checks, not installed
acceptance. The supplied POST405 implementation is not modified by this package.

Exact prior head `6bd9bd1` failed Actions run39996108969/job120559939443 at
`tools/verify_separation.py`, before tests/build: the unreleased bundle kind
accidentally matched the existing credential-format scanner substring. This
revision renames it to `observation-bundle`; the guard is unchanged. Its original
JSON/hash changes, so the private partial export must use the corrected kind.
The source regressions workflow now includes observation, passive adapter,
report/import and Node helper tests. A Linux check does not imply Windows CI or
native E2E success. Chromium remains unavailable after the official installer was
blocked by policy at cdn.playwright.dev; no bypass or Mac fallback is attempted.
