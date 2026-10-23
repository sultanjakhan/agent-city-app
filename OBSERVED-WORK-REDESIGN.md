# Passive observed-work frontend candidate

Independent new components for the existing native webview. This branch is based
on `32ed8df` and targets `work/portable-report-preparation` so PR #23 is preserved.
No installed legacy frontend source, runtime data, native IDs, private descriptor,
logs or settings belongs in this checkout or public artifacts.

## Product and page contract

| Page | Object and purpose | Navigation |
| --- | --- | --- |
| Главная | Current authoritative Cicada tasks and explicit unresolved requests for an answer/approval. Attention precedes current work; a task appears once. | Task → exact linked executions → existing observation detail; unlinked tasks have a read-only task view. |
| Проекты | Select a project; see current observed agents, counts and explicitly recorded relations. Agent IDs remain source-scoped observations, not persistent invented identities. | Agent → current observations; project history opens the global filtered collection. |
| История | One row per returned completed/interrupted observation. Raw session's last turn ending is inactivity, not conversation closure or task acceptance. | Project filter → same observation details. |

Cicada exclusively owns tasks, timers, lifecycle and acceptance. The frontend
never writes native data or infers a task match, blocked/waiting/success from
silence. Unknown source coverage is separate from execution status. Empty Home means current work is not confirmed in the selected Cicada source, not that all work everywhere has stopped. Failed, disconnected and partial sources retain qualified last-known rows instead of implying an empty complete result. Local collector coverage does not prove cloud ingestion.

Details show one task title, short project/agent/session breadcrumb, compact
Время · Токены · Модель summary, secondary start, token breakdown disclosure,
compact reported skills, and timestamped activity. Exact identity/provenance is
secondary; there is no invented task URL, Usage/Skills detail page, token price,
model speed, or billable claim. Genuine multiple turns remain expandable. A sole
bound turn gets no artificial wrapping group. UI copy is Russian; source model,
skill and identity values remain exact.

## Home projection contract

`observed-tasks.js` joins only full explicit profile/sourceKey/sourceId/taskKey
bindings. Same titles and UUIDs do not create links. Process labels remain source
facts, not projects. Timer-active non-completed tasks, exact observed current
executions, or exact-task running/waiting reports within 300 seconds (30 seconds
future skew) qualify as current. Paused-only or planned tasks do not.
Latest reports are selected by sequence per originDevice/runId. Only latest
waiting reports with user_input/approval request attention; those requests do not
expire with heartbeat age. A newer terminal report resolves them. Ordinary
waiting, errors and failed verification do not imply a request for a person.
Source changes isolate report namespaces; open old-source selections retain
explicit old-source facts without current timer claims. Counts stay unknown
without explicit linked current observations. There are no portfolio metrics,
question fabrication, result URL actions, or task mutation controls.

## New public modules

- `static/observed-tasks.js`: pure task projection and keyed compact task master/detail, using the existing dashboard source only.
- `static/observed-work.js`: pure normalized state model plus keyed DOM component;
  `createModel`, `mount`, `parseRoute`, `formatRoute`, `timing` exports. No transport
  or persistence. `mount(root, {initialRoute, onRoute, externalNavigation})` returns
  `update`, `navigate`, `destroy` and the model.
- `static/observed-work.css`: scoped light responsive components using existing
  public semantic tokens, tabular numbers, bounded status column, wrapping long
  model/skill/identity values and responsive metrics/event grids.
- `static/observed-feed.js`: pure mapping from LiveSessions metadata plus a
  cached-reader/subscriber connection. Keeps raw session scope vs exact-bound-turn
  scope; never flattens every raw turn into task attempts or duplicates a bound
  row. Unknown counters remain null, zero stays known; cached input/reasoning output
  remain subsets, never added again. It never reads `session.skills` as application.
  Applications require an exact bound turn, binding.skillSource executor-reported,
  skillsKnown true and an explicit skill-applied executor-reported activity event.
- `static/observed-host.js`: opt-in adapter around the existing `window.LiveSessions`
  cache, visibility lifecycle, navigation hooks and summary event, plus the existing lexical dashboardData/dashboardReadError cache and original loadDashboard lifecycle. It hides legacy
  duplicate Home/session surfaces and adds History navigation. Models, Connections
  and Limits retain their handlers. The original dashboard loader retains its single five-second visible-Home schedule; LiveSessions retains its observation schedule. Old dashboard rendering stays hidden; there is no extra polling, fetch, endpoint or daemon.
- `compat/observed_frontend.py`: assembles these newly authored modules into the
  two already-served LiveSessions JS/CSS assets. No static allowlist change.

Normalized metadata includes projects/agents/explicit edges and sessions with
stable IDs, projectId/agentId, observed status, explicit scope `{kind,id}`,
coverage, nullable measurements, optional structured task identity and explicit
applied events. `normalize` is a display boundary, not native authorization or
an import/report validator. Input arrays are copied and unsupported fields are
not rendered; callers must provide only metadata approved for this view.

## Polling and state preservation

Updates patch nodes by stable identity. Session/agent/map ordering is stable
across source reorder; timestamp-sorted activity reconciles late earlier events
by moving the same DOM nodes and preserving focus/scroll. Updates do not reset
routes, close selected finished observations,
scroll into view or call onRoute. Tabs support ArrowLeft/Right/Home/End with focus movement. Main tabs, disclosures, focus, scroll containers
and genuine turn nodes stay in place during polling. If a selected row disappears,
its details show unavailable without silently selecting another row. Explicit
user navigation may change the selection. The host continues its existing polling
cadence; this component introduces no second loop.

At narrow widths below 800px, a selected detail replaces the list. The explicit
«Назад к списку» action retains page/project/agent filters, restores the saved
list position and focuses/reveals the selected row (or the list heading if that
row is no longer listed). Desktop retains the split view. Feed updates never
trigger this return path. Raw rows show the supplied agent with session name;
bound task titles remain primary. History sorts by ended timestamp descending,
then exact observation ID, with unknown dates last; keyed nodes stay intact.

## Private compatibility assembly and install boundary

Original installed files were approved only for private compatibility inspection,
not publication. Keep them and assembled outputs outside git/public artifacts.
Do not commit full copied legacy files or screenshots containing private metadata.
The assembler reads only explicit `static/live-sessions.js` and
`static/live-sessions.css`; optional private input hashes guard source identity.

```sh
python -m compat.observed_frontend --baseline /private/approved-source-copy --output-dir /private/new-review-copy --expected-hashes /private/asset-hashes.json
```

The output directory must be new and outside git. Inputs are unchanged. Output is
complete PRIVATE planned assets containing the original source plus the new
bundle/styles; never upload those files publicly. Baseline content is neither
printed nor included in public tests. Existing exact-turn runtime modules and
binding file are untouched. Assembly adds no script/style URL, credentials,
write capability, server policy change or installed switch. Boot waits for the
host's passive_dashboard mode and complete shell initialization. Root reviews
these two private assets, recomputes runtime pins/descriptor and performs any
separately approved installed switch. Preserve every POST405, readOnly true,
discovery false and cloud false.

## Evidence and remaining review

Node tests execute the actual model, mapper, keyed renderer and host adapter with
synthetic metadata and a small DOM recording harness. They cover scope/unknowns,
read vs application, no native task/timer mutation, selection after completion,
route stability, focus, disclosures and scroll preservation. Task tests additionally cover exact identity isolation, attention/current deduplication, latest-report resolution, freshness/skew, incomplete/failure/recovery, source switches with open details, unknown counts, no-session tasks, task/execution/back flow and reuse of the old loader schedule. The DOM harness is
not a browser/layout oracle. Python tests cover the actual two-asset assembler,
byte-identical originals, UTF-8, explicit input hashes and duplicate assembly
rejection. These tests use no private baseline files.

`tests/observed-ui.spec.cjs` and `playwright.observed.config.cjs` provide a separate
synthetic browser regression and screenshots at 1280, 700 and 390px. Cloud Chromium
is absent; the official installer was previously denied by network policy. No
bypass or local fallback. Browser behavior/screenshots and installed compatibility
are unverified until their respective checks run. The dedicated PR workflow runs
Node/Python source regressions on cloud Linux and Windows, not installed E2E.

The named product-review/ux-design/ui-design skills are unavailable in this lane's
skill catalog. Implementation follows the coordinator's supplied product/UX/UI
contract and public design tokens; it does not claim separate skill applications.
