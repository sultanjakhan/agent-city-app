# Project policy integration contract

Optional policies map keyed by repo ID in repository-profiles.json; envelope schemaVersion remains 1 and legacy profiles remain lists of extension IDs. Uses existing bounded, atomic, revision-checked RepoProfiles storage and /api/repositories/profile save API, accepting optional policy. Omitting policy preserves saved policy. No migration or seeded policy values.

```json
{"schemaVersion":1,"instructions":"","sourceIds":[],"allowedActions":[],"deniedActions":[],"defaultPipelineId":null}
```

IDs are opaque references, never URLs, credentials or permission grants. An empty project allow list permits no actions in preview. Deny wins. Missing child fields inherit; explicit empty child lists restrict everything. Source lists intersect. Pipeline then stage can only restrict the current ceiling. Attempts to expand it and allow/deny conflicts are returned explicitly, alongside the effective restrictive result.

`POST /api/projects/policy/preview` accepts `{policy, pipeline?, stage?}`. Child objects contain only optional sourceIds, allowedActions, deniedActions. The pure `project_policy.preview_policy` function is the integration point for Architecture; model routing and step budgets remain there. Data sources resolves sourceIds against its own catalogue and authorization. Default pipeline is optional and does not require manual tasks to use one. The UI offers transient child restriction JSON for conflict preview; these restrictions are not stored as project policy.

Actual support: metadata persistence, validation and declarative preview only. runtimeEnforced=false. No runner consumes these labels today, no sandbox enforcement, no granting permissions, no connector calls or credential handling. Source and pipeline existence and actual access are not verified. Runtime integration must independently enforce existing authorization and resolve these references before execution. Instructions are text, not executable policy or an override of repository/system rules.
