# Changelog

## 0.5.23

- Include the application's MIT license in the signed Windows package.
- Build from a clean public checkout using locked dependencies in the explicit
  build directory; remove dependence on a previous checkout's restore output.
- Keep the existing SQLite-based Cloudflare activity relay source in this same
  repository, with Free-plan constraints and separate data/credentials documented.
- Release the Windows package from its exact public source commit.

This release does not migrate data or enable provider/cloud connections by itself.
