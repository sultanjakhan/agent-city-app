# First public release: 0.5.22

This repository starts with a clean source export. Earlier development history
and private working data are intentionally not included.

The Windows 0.5.22 package was built from development commit
`775b1745b7b3c4313b3c5eb62ab1f651c73af2c9`. The exported source snapshot was
`c1ad77b42f076025bd6a87bdd2762d2fd720133a`: its only changes after that build
were `tests/fixtures/native-copy-baseline.json` and
`tests/native_host_wiring_contract.py`, making source checks independent of the
old Git history. Application sources are identical. MIT licensing and public
documentation were added to the exported snapshot before publication.

The tested Windows update archive is
`agent-city-windows-x64-0.5.22.zip` (13,749,022 bytes), SHA256:

`25c43d3bae94d2ccaa841ab10ed233072f2dad33b73698e17e0ef37a6798b945`

The app pins the RSA public key in `desktop/UpdateTrust.cs`. Its signed
`latest.json` binds the archive name, size, hash and version. A real existing
Windows installation upgraded from 0.5.21 to 0.5.22 through this signed package,
keeping the same executable path, shortcut, settings and activity data.

First installation on another computer, macOS, and recovery from power loss
between directory renames have not been verified. A public-channel check of an
already current version does not prove a future upgrade from GitHub.


## 0.5.24

The public source includes the final installed API/shared-task/background/UI
checkpoint `dade11df42d048c578cc3c0485ced820442934b7` as a source snapshot,
without importing its private Git history. Public documentation, licensing and
the separate encrypted Cloudflare relay are retained.

This release adds guarded, owner-requested data-folder relocation on normal
close and native CLI access through the current-account pipe. Original data is
retained; folders are never automatically merged or deleted. A live backend
writer blocks relocation. Provider credentials and Cloudflare keys remain outside
Git and release packages. macOS Keychain alias logic has unit coverage only;
physical Mac acceptance remains separate.
