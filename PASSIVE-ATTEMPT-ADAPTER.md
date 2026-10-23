# Frozen passive LiveSessions exact-turn adapter

This package adapts the supplied frozen interfaces; it does not replace the
installed full server. Preserve verified ProductionBinding, readOnly=true,
discovery=false, cloud=false, the GET allowlist and every POST405. No HTTP writer,
daemon, native mutation, credential enrollment or journal reader is added.
Nothing here has been installed or accepted on Mac.

## Reviewable source splice

`compat/frozen-exact-turn.patch` contains the complete splice against the supplied
anchors and two new modules. `compat/frozen_patch.py` reproduces it and performs a
read-only unique-anchor preflight. Run from this checkout in cloud against a NEW
copy of the frozen source tree (not the frozen installed runtime or foreign WIP):

```sh
python -m compat.frozen_patch --check-root /path/to/new-frozen-source-copy
git -C /path/to/new-frozen-source-copy apply --unidiff-zero --check /absolute/path/to/compat/frozen-exact-turn.patch
git -C /path/to/new-frozen-source-copy apply --unidiff-zero /absolute/path/to/compat/frozen-exact-turn.patch
```

The preflight is required: these limited-context hunks come from exact supplied
excerpts, rather than full frozen files. Stop if an anchor is absent/ambiguous,
files already exist, or patch checking fails. Do not force an incompatible splice.
The preflight reads and simulates changes without writing. The coordinator owns
assembly of a fresh runtime copy, source pins/descriptor, approved backend restart
and installed checks. Do not copy public `server.py` over the frozen server.

The patch changes only:

- `passive_server.py`: wraps the existing collector assignment with
  `BoundLiveSessions`, sessions path `('sessions',)` and routing identity fields
  `projectId`, `agentId`, `parentId`. Store construction and server policy stay intact.
- `native/agent-system/app/live_sessions.py`: adds per-turn singular model/effort,
  explicit observed start, coverage, last event and duration provenance. Optional
  cachedInput/reasoningOutput appear only if measured usage already contains them.
- `native/agent-system/app/cicada_connector.py`: adds only `personalEligible` to
  existing task metadata. Exact guard: literal `task-sphere:personal` token and no
  case-insensitive work token or jira/investlink prefix. No extra query or write,
  and no arbitrary tags exposed by the splice.
- `native/agent-system/app/static/live-sessions.js`: calls the formatter inside
  the actual `patchMetrics` function and stage metric assignment. Existing
  incremental rendering, routing and disclosures remain in place.
- `native/agent-system/app/static/index.html`: loads `/passive-attempt-view.js`
  immediately before the supplied `/live-sessions.js` script line.
- New app `passive_attempts.py` and static `passive-attempt-view.js` modules.

## Exact bounded attribution

The wrapper reads at most 16 KiB from the single owner-authored
`passive-attempt-binding.json` in the panel directory. It never creates the file
or writes a store. On each projection it rereads the binding and calls the
existing connector `snapshot(task_keys=[exact taskKey])`. Connected source,
profile, sourceKey, original sourceId, connector taskKey and
`personalEligible is True` must all match fresh data. Optional nativeTaskKey is
kept separately and must have exactly the bound sourceId suffix; namespace and
path-hash keys are never inferred equivalent. Title/UUID alone cannot bind.

Only the exact session and turn are projected. Unrelated sessions and the input
snapshot remain unchanged. Missing/duplicate turn, invalid identity, absent
personal eligibility or changed source leaves the row unlinked with an
unavailable diagnostic. Preserve root project/agent/parent identity. Session
metrics, model, timestamps, current action and past turns cannot supply missing
turn evidence. Directory summaries remain collector data, not draft usage.

Collector timestamps accept explicit timezone-aware ISO8601 offsets and normalize
to UTC. Naive, invalid, future or contradictory/order-invalid timestamps fail
closed. The collector's `startedAt` first-seen fallback is never substituted for
`observedStartedAt`. Exact host statuses working/completed/interrupted/unknown
are preserved. A working turn can show clearly labelled running elapsed derived
from its observed start; this is not completed duration. Completed duration is
labelled either collector-reported or derived from observed turn bounds. Unknown
stays null/Unknown; receipt/import times and thread totals are never used.

The plain-text task field displays original task title, all four exact connector
identity fields, optional native key, bounded turn identity and provenance. A
completed/stopped attempt never completes its Cicada task or changes its timer.

## Owner-authored binding

Strict JSON with exactly these fields (runtime identifiers never belong in public
source, fixtures or PR text):

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

Unknown fields, duplicate JSON keys, redirected paths and oversized input are
rejected. Skill reads/inventory do not imply application. Only explicitly
executor-reported applied records for this turn are projected, labelled
**executor reported**, not independently verified. Null means unknown; an empty
list means none reported. Known turn bounds constrain reported event times.
No prompts, messages, hidden reasoning, tool arguments or raw logs are imported.

The coordinator supplies the real root current-turn binding through its authorized
file workflow. The worker metadata snapshot is not a root-turn binding. Do not
invent an observed turn ID or copy historical thread tokens/model/time. Actual
per-turn usage and applied-skill evidence unavailable to this cloud executor
remain unknown. This splice is not authenticated remote delivery.

## Synthetic cloud evidence and CI

`test_passive_attempts.py` exercises the actual read-only connector with temporary
SQLite data and actual offset/working-shaped synthetic collector rows. It checks
exact scope, personal guard, native suffix, timestamp validation, unknowns,
reported applications vs reads, fresh revalidation, unchanged unrelated sessions
and byte-identical task/timer data. `test_frozen_patch.py` applies the generated
patch to synthetic supplied-anchor files, executes the patched collector and
connector fragments, and runs the actual patched patchMetrics in Node.
`tests/passive-attempt-view.cjs` checks timing and formatting. These are synthetic
cloud checks, not installed UI or real telemetry acceptance.

Prior head `6bd9bd1` failed Actions run39996108969/job120559939443 in the separation
scanner: the unreleased bundle kind accidentally matched its credential-format
substring rule. Renaming it to `observation-bundle` fixed the collision without
changing the guard. Parent head `ad4bb10` Windows candidate run39999199063
succeeded; that is candidate build evidence, not native E2E or a result for later
heads. New candidates need their own CI result.

Chromium UI behavior remains unverified: the official cloud installer was blocked
by network policy at cdn.playwright.dev. No bypass or Mac fallback was attempted.
Remaining installed acceptance requires the coordinator's verified current-turn
binding, fresh selected-source read, updated pinned runtime copy and approved
passive backend/UI check, including POST405 and unchanged task/timer data.
