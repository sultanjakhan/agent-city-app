# Changelog

## 0.5.25

- Allow Russian task results to reach Cicada through a 64 KiB task-request
  budget and a 256 KiB trusted internal envelope. Ordinary control limits and
  access checks remain unchanged.
- Stop oversized frames before their remaining bytes can become another request.
- Keep native pipe and MCP helpers aligned with the task-request budget.

## 0.5.23

- Include the application's MIT license in the signed Windows package.
- Build from a clean public checkout using locked dependencies in the explicit
  build directory; remove dependence on a previous checkout's restore output.
- Keep the existing SQLite-based Cloudflare activity relay source in this same
  repository, with Free-plan constraints and separate data/credentials documented.
- Release the Windows package from its exact public source commit.

This release does not migrate data or enable provider/cloud connections by itself.
