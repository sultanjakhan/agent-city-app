# Published work exchange v1

Agent City 0.5.19 consumes explicitly imported published snapshots and paired
Cicada executor reports. This is an offline observation and telemetry feature.
It does not launch tasks, models, MCP tools or Jira actions.

## Storage and authority

`work-exchange.json` and `agent-runs.json` live in the configured external panel
storage. No private pointer, native database, profile, key or task text is embedded
in application code. The consumer reads only the selected configured native
Cicada SQLite source using read-only/query-only access. Production and DEV remain
separate approvals, including when a copied database has the same namespace.

Pairing requires a producer-created `calendar_task_run_exchange_v1` namespace,
an exact existing binding and an existing unarchived native task. Agent City
never creates that namespace, binding, task or database. Stable taskKey is
`cicada-` + first 16 hex characters of SHA256(full lowercase namespace UUID,
including hyphens) + `-` + unchanged native sourceId. Existing path-based taskKeys
and reports remain readable as legacy aliases; no historical record is rewritten.

A user selects a bounded UTF-8 JSON file, requests a read-only Preview and then
separately confirms Apply. The receipt expires after ten minutes and binds the
validated document, current storage revision and selected native source. Apply
rechecks the source. Conflict or failure retains the file draft and requires an
explicit new Preview; it never silently retries a write.

## Accepted envelopes

- `cicada-task-binding`: schemaVersion 1, kind and exact binding fields
  sourceNamespace, sourceType `note`, sourceId and taskKey.
- `cicada-run-report`: the above binding plus the existing strict RunStore report.
  Sequence is monotonic, identical replay is idempotent, executor identity is
  immutable, cumulative token/MCP counters cannot decrease. Null stays unknown.
  No prompts, arguments, results, credentials or arbitrary fields are accepted.
- `work-registry-snapshot`: exact producer schema v1, published-snapshot mode,
  source publisherId/namespace, projects and hierarchical tasks, with empty runs.
  Unknown fields, duplicate IDs, cycles and invalid references are rejected.
  A newer full snapshot replaces only that publisher/namespace projection.
  Omitting a task removes its observation card, never its native task or history.

Raw JSON is bounded to 1 MiB, strict UTF-8, no duplicate keys, nonfinite values or
excessive nesting. Storage is bounded to 4 MiB, 500 bindings and 20 publishers.
Native identity metadata is independently bounded; malformed optional exchange
metadata leaves the legacy task view available but prevents pairing/import.

## What the UI means

Published status, provenance, publication/receipt dates and freshness are shown
separately. Freshness is recalculated from lastUpdated and the published policy,
including on dashboard polling. Future timestamps yield unknown. A stale source
never changes a recorded status into failed. Published done or executor done never
marks a native task completed. Cost and unobserved time/usage remain unknown.
Disclosure state survives polling, search uses current observations and labels are
rendered as text. Export includes only the strict report envelope and paired
binding; it contains no native task text or history.

Publisher metadata is not cryptographic authentication or proof that a statement
is true. A user-chosen snapshot remains a publisher's observation, not live state.
There is no automatic republication, dispatcher, shared transactional allocation,
launch endpoint, authenticated cross-application transport or real execution.

## Launch contract boundary

The existing pure launch-intent contract uses shared task UUID and request UUID
for origin-neutral runId, and an immutable detached pipeline snapshot/hash.
Published task IDs and legacy/native sourceIds are not automatically shared UUIDs.
The separate synthetic local-dispatch prototype is not connected here: its states
succeeded/failed and cost/duration telemetry need an explicit adapter to the strict
RunStore schema. A durable authoritative binding, authenticated admission, real
budget enforcement and executor capability checks require separate scope.
