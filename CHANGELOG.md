# Changelog

## 0.5.27 — combined cloud candidate (not published)

- Add same-account native update status/check and exact-source idle-close requests, with draft/uncertainty deferral and the existing verified graceful updater path.
- Require a native business task binding for automatic lifecycle hooks; preserve bound reporting and retain unbound legacy requests without retrying task creation.
- Retain exact task/operation/run identity when launch or sync receipts name another task; keep drafts for safe replay.
- Return private owner-process setup failures without leaking exception arguments; reject redirected writer locks without replacing active lock files.
- Prevent automatic cross-provider retries after a model request was sent; treat empty environment keys as unavailable and redact key-save failures.
- Include the merged catalogue persistence rollback so failed writes retain prior payload/date while exposing the failed attempt.
- Review the unchanged public application icon by exact path/hash while retaining fail-closed privacy/binary scanning.

## 0.5.26 — release preparation (not published)

- Combine explicit reported-model display, truthful integration observations, the own-held migration-lock fix, and project/tag/current-history filtering from PR #13.
- Align application, UI and native version metadata without replacing the separate pending 0.5.25 candidates or draft 0.6.0 release.
- Validate unsigned Windows QA candidates on hosted compute. Existing-key signing, signed release publication and installed-device acceptance remain separate.

## 0.5.23

- Include the application's MIT license in the signed Windows package.
- Build from a clean public checkout using locked dependencies in the explicit
  build directory; remove dependence on a previous checkout's restore output.
- Keep the existing SQLite-based Cloudflare activity relay source in this same
  repository, with Free-plan constraints and separate data/credentials documented.
- Release the Windows package from its exact public source commit.

This release does not migrate data or enable provider/cloud connections by itself.
