# Pipeline architecture schema / coordination handoff

Integrated candidate 0.5.18: declarative editor, repository policy preview and
prepared task/run snapshots. Active runtime is not switched by this change.

Pipeline v1: exact keys schemaVersion, id, name, projectId, limits, stages.
Stage: id, name, kind (work/review), modelRefs [catalog IDs], skillRefs [inventory IDs],
limits, transitions. First stage is entry; review must be reachable in preview.
Transition: when (success/failure/limit/reviewRejected), action (next/stop/escalate),
target (stage ID for next; null otherwise). Escalate requests human review; it
cannot automatically select a paid provider or grant access. Graph cycles are
allowed declaratively; executor semantics/bounded traversal are not implemented.
Limits: optional nonnegative tokens, costUsd, timeSeconds, retries. Except costUsd,
values are integers. Missing inherits upper bound, zero means zero.
No prompts, task text, credentials or provider access in this schema.

Project policy is read from repository-profiles.json using the exact repoId in
projectId. The shared project_policy.preview_policy computes action/source
restrictions: deny wins; pipeline/stage can only narrow the saved ceiling.
Client-supplied projectPolicy is rejected by HTTP. Missing saved policy infers
no authorization. Project budgets are unknown because the existing policy has
no budget fields. Pipeline/stage limits are advisory configuration bounds;
stage limits may only tighten configured pipeline bounds. Missing bounds stay
null. Save stores drafts, including conflicts; it never activates execution.
No launch endpoint. canRun is always false. configurationValidation supported;
externalClient unknown; actual token/cost/time/retry enforcement advisory.

Storage: <external panel data>/pipelines.json; SHA256 optimistic revision,
atomic replacement under process lock. User configuration never in application
code. GET /api/pipelines; token protected POST /api/pipelines/preview and /save.
The current implementation is single server writer, consistent with local stores;
multiple processes are not an approved runtime.

Both Cicada and Agent City may originate task/run requests in a shared model.
Task identity and status belong to that shared model; technical stages here must
not duplicate the task editor. Agent City owns technical pipeline configuration
and reported telemetry. No current Cicada writes; no inference, install, credentials, push or runtime
switch. Model selection is a reference only, never evidence of availability.

## Bidirectional task/run intent contract (updated user decision)

`task_launch_contract.prepare_intent` accepts origin cicada or agent-city, a
shared opaque taskId, immutable requestId and pipelineId. It produces one runId
from the taskId/requestId pair, independent of origin: a retry through the other
UI maps to the same run. New execution attempts MUST use a new requestId. This
is a pure preparation function, status prepared, executionSupported false. It
does not create/update Cicada tasks or submit inference.

Before integration, the parent must agree a shared task registry, persistent
task UUIDs and status owner with Cicada. Never derive task identity from titles
or database paths. Both entrances use the same registry/dispatcher. Carry the
origin as metadata, preserve requestId through forwarding, and deduplicate by
(taskId, requestId); status reflections never create launch requests. Actual
running/waiting/done/error/cancelled updates still use RunStore sequence rules,
and must not mark a task complete automatically. Existing path-hash taskKey
requires an explicit registry binding to taskId before reporting. This contract
is prepared; cross-app status synchronization is not implemented.

## Compatibility with project-policy fc5a51a

Existing policy is stored ONLY in repository-profiles.json through RepoProfiles,
keyed by repoId. Architecture projectId must bind to that exact repoId. Existing
policy keys: schemaVersion, instructions, sourceIds, allowedActions, deniedActions,
defaultPipelineId. There are no budget or projectId fields; limits are rejected.
Existing child restrictions accept only sourceIds/allowedActions/deniedActions,
so pipeline budgets/modelRefs/skillRefs cannot be passed to preview_policy.

Minimal adapter pipeline_policy_adapter.preview_repository_pipeline reads
repo_profiles.read(pipeline.projectId).policy/revision and invokes the existing
project_policy.preview_policy. No second policy store, copied validator or
invented defaults. Missing saved policy infers no permission. Stage restriction
metadata is transient. Project budget ceiling remains unknown: a jointly
versioned extension to the existing policy schema is required, not another file.

The adapter is wired into server/UI. Tests use the actual integrated
project_policy function and RepoProfiles through the HTTP route. All runtime
authorization remains independent; runtimeEnforced and canRun stay false.

Shared registry must persist pipelineSnapshot and pipelineSnapshotHash once per
request. prepare_pipeline_intent makes a detached validated snapshot; later edits
cannot change it. Same requestId with changed payload/hash must conflict in the
registry, never overwrite. Both origins use the same dispatcher/registry; status
reflection never creates requests. cancel_requested is a request; cancelled needs
executor acknowledgement. stale is observation freshness, never failed execution.
No dispatcher/status synchronization/registry persistence is implemented here.

Parent navigation research: Projects / Catalog / Architecture / Tasks; budgets
inside pipeline, sources Settings. This branch retains only the already approved
Architecture addition, leaving full navigation restructuring to integration.

## Integrated HTTP authority

The pipeline preview/save routes now read RepoProfiles by pipeline.projectId
(existing repoId), then call the shared project_policy.preview_policy function.
Client-supplied projectPolicy is rejected; optional pipelineRestrictions and
stageRestrictions are transient narrowing layers. No independent project policy
or budget is stored. projectBudgetSupport remains unknown. The Architecture UI
shows the saved policy projection and has no simulation policy input. Save
stores only the pipeline configuration. Execution and permission enforcement
remain unsupported. Snapshot/hash preparation is pure and does not dispatch.
