# Changelog

## 0.6.0 — release candidate

- Use nine left navigation sections, with a drawer on narrow screens. Models
  opens subscription limits; Providers has its own section.
- Keep Dashboard limited to current tasks. Open a task in the main workspace,
  with Overview, History and Context tabs and stage details below the selector.
- Preserve task identity across Cicada, shared-task and observed-run projections.
  Aggregate concurrent attempts without treating a completed attempt as the end
  of another executor's ongoing work.
- Use the existing neutral palette, text actions and subtle highlights. Remove
  accordions and keep edits protected while changing task or process views.
- Store shared, versioned standards separately from project references. Projects
  can select an exact version; selection does not apply CSS or execute checks.
- Show local hardware facts and actual storage locations without exposing keys.
- Include the pending 0.5.25 task transport and draft lifecycle fixes from PR #9.

The Windows package and signed update assets must be built and accepted before
this candidate is published to the stable update channel. Process editing remains
configuration only; a pipeline executor is not connected in this release.

## 0.5.23

- Include the application's MIT license in the signed Windows package.
- Build from a clean public checkout using locked dependencies in the explicit
  build directory; remove dependence on a previous checkout's restore output.
- Keep the existing SQLite-based Cloudflare activity relay source in this same
  repository, with Free-plan constraints and separate data/credentials documented.
- Release the Windows package from its exact public source commit.

This release does not migrate data or enable provider/cloud connections by itself.
