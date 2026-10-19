# Scoped local context (candidate contract 1)

The file itself is the source of truth. `context-grants.json` is a small local
atomic/CAS configuration. `context-index.sqlite3` stores only relative paths,
opaque IDs, kind, size, mtime, hash, metadata description and index time. It has
no document bodies, keys, task text or cloud transport. It can be removed and
rebuilt; grants survive. After rebuilding, search again before reading an ID.
The cache helps repeated searches; the first scan reads allowed text to hash it.

Only this local device is registered. A foreign device ID returns
`device_unavailable`; relay access and remote file reading are not implemented.
Grants and local paths stay outside Git and outside the encrypted report relay.

## Host configuration and agent flow

Run host grant commands from the reconciled app directory against an explicitly selected existing private profile. HTTP routes retain the current owner-session/delegation requirement; unauthenticated loopback requests return 401.
The installed CLI/MCP must be upgraded separately before using these commands
against production. A root path is host configuration, never an HTTP/MCP input.

```text
python city.py file-roots --port <isolated-port>
python city.py grant-root --data <absolute-private-profile> --path <absolute-approved-root> --label Documents --revision <grants-revision>
python city.py file-search --port <isolated-port> --device-id <device-id> --root-id <root-id> --kind skill --q task-execution --limit 1
python city.py skill-inventory --port <isolated-port> --device-id <device-id> --root-id <root-id> --id <skill-id> --revision <file-revision> --start-line 1 --end-line 30 --max-bytes 8192
python city.py revoke-root --data <absolute-private-profile> --root-id <root-id> --revision <grants-revision>
```

`GET /api/v1/devices` and `file-roots` enumerate choices.
The new `file-roots` HTTP/MCP response exposes root IDs, labels, source and status,
without the private `path`/`canonicalPath` fields or absolute suggestion paths.
Full root paths remain in local grants configuration for host grant and secure
reading. Existing legacy repository/context APIs retain their path metadata;
this projection does not claim path secrecy across those older APIs.

`file-search` requires
deviceId/rootId, supports q (path/name/description), kind, extension, limit
(default 20, max 50), offset and revision. It searches metadata, not document
bodies. `file-read` takes the enumerated ID, revision, startLine/endLine (at most
200 lines), maxBytes (at most 32768) and byteOffset. Skill IDs reuse
`SkillInventory`; its existing `/api/skill-inventory` reader accepts the same
scope and bounds. The existing inventory/editor retains its previous fixed
skill roots; scoped grants do not redefine that pre-existing UI authority.

For a truncated window, preserve its start/end lines and revision and continue
with nextByteOffset. This progresses inside a single long UTF-8 line too. A byte
limit smaller than the next character returns an explicit error. To move to the
next line window, reset byteOffset to zero. Revisions hash source bytes, while
returned text uses UTF-8 and removes a BOM if present.

An indexed hash is explicitly a snapshot. Search refreshes stat metadata and
rehashes changed size/mtime; read always hashes current opened bytes. Deliberately
preserving size and mtime can leave the index snapshot old, but a revisioned read
returns `file_changed` with the current hash. Missing files, revoked grants,
redirected roots, invalid IDs and stale index pages have distinct errors.

Junction/8.3 aliases can be registered by the host: their canonical target is
pinned. Retargeting invalidates the grant. Nested reparse nodes and hardlinks
are denied; arbitrary path, UNC/device paths, shell and URL arguments are absent
from the public tools. Open handles are checked against pinned roots. This is
a local read authority, not protection against a hostile process with the same
OS user's ability to modify the grants configuration.

Repository suggestions reuse `RepoInventory`; workspace skill suggestions reuse
`SkillsStore`. Suggestions do not grant access. Plugin discovery in the existing
plugin cache does not depend on vendor names: at most 32 namespaces, 64 plugins
per namespace, 8 versions and 256 root records. Each level rejects reparse nodes.
Cache membership means cached source, not proof that a plugin is currently active.
Matching hashes in two separate source files do not prove their canonical origin.

## Model pages

`GET /api/v1/models` returns 20 routes by default, at most 50. Filters:
q, provider (exact), developer (substring), kind, tools, vision, priceVerified,
authStatus, responseStatus, offset, revision. Booleans are `true`/`false`.
Catalogue revision includes catalogue/source/auth/check evidence and excludes
response time. A stale revision returns HTTP 409 with the current revision.
Catalogue, verified-price snapshot, key/auth evidence, unknown quota and dated
inference result are separate. No route list launches a model or proves a free
account quota or task quality.

## MCP connection and installation boundary

`python context_mcp.py` uses the existing installed native authority by default.
An explicit `--port` selects legacy loopback HTTP and does not manufacture an
owner cookie or grant. An unavailable/denied native request does not fall back
to HTTP. The original `city.py` native and owner-delegated stdin transports are
retained. Synthetic transport tests bootstrap a private fixture owner session
and pass that fixture authority over inherited stdin to their stdio adapter. It exposes devices, file roots, file/skill search and read, and
model pages. Its tools cannot configure grants or select an endpoint.

The existing installed `agent_city_*` tools belong to the Cicada plugin's
`vendor/agent_mcp.py` and use the AgentCityAgent named pipe. This candidate does
not overwrite that plugin or restart the installed backend. The standalone MCP
tests prove the candidate protocol and HTTP authority; they do not prove that
the installed plugin exposes these tools. Integration must add the same bounded
schemas/routes to that vendor bridge and permit them in the installed backend's
native transport. The current native allowlist already accepts models and versioned skill-inventory;
this integration adds devices/file-roots/file-search/file-read as GET-only reads
to both current-user native and exact owner-delegation allowlists. Backend query,
grant, revision and file safety checks still apply. No grant/revoke agent route exists. Existing inventory model calls receive a bounded page;
clients needing the whole catalogue must follow nextOffset with the first revision.
HTTP 409 requires restarting the catalogue read, without launching inference.
Do not replace the newer installed backend with this older feature-base checkout.

## Verification

```text
python -X utf8 -m unittest discover -s tests -p test_context_http_mcp.py -v
python -X utf8 -m unittest discover -s tests -p test_skill_inventory.py
python -X utf8 -m unittest discover -s tests -p test_model_query.py
python -X utf8 tests/measure_context.py --output <private-results.json> --real-skill-root <approved-skill-root>
```

Transport tests start actual isolated HTTP and stdio MCP processes. External
credentials and clients are fixture dependencies; FileContext, SkillInventory,
HTTP handlers and MCP wire messages are real. Windows junction tests use inert
temporary files; no production profile, model inference or windows are touched.

## Source reconciliation boundary

Reconciled from verified candidate `90d6e068ce71d2b414358538d5afdc67310888a8`
(full patch SHA256 `e9cd47e1481c5a3fd0d0d1d43f8a9636d2fcc80593a0a32c6b3a130dca329139`)
onto public source `250401bad7c52029d92351f6da10ff70e4c814ae`. The historical
API.md is absent on that source; its partial patch was not used to invent a
replacement document. The pagination contract is retained above. No frontend
files, policy labels, authentication gates or installed plugin files change.

New grants/lock/index state rejects redirected paths using the existing repository
path guard; SQLite sidecars are checked too. This fixes a synthetic reproduction
in which a pre-existing context-index.sqlite3 symlink caused SQLite to create
state outside the private profile. It does not claim isolation from a hostile
same-account process racing filesystem changes. RPC nesting is explicitly bounded
independently of the Python interpreter's recursion limit.

Source checks use temporary synthetic grants/files and actual authorized fixture
HTTP/stdio processes. Windows junction execution, installed native/plugin tool
exposure, signing, supported update and installed end-to-end acceptance remain
separate gates. Source verification does not satisfy them.

## Plugin bridge handoff

The standalone `tools/agent_mcp.py` now exposes the same seven bounded context
schemas without importing backend modules. It retains all existing Agent City
and Cicada tools. `tools/plugin-context-read.patch` is an additive patch for the
separately owned Cicada plugin's `vendor/agent_mcp.py`, not a replacement bridge.
It was applied and imported in isolated cloud scratch against source SHA256
`e8b2dad216b317dcf481d4fe502bcd19287c9ed82871414c14e1f5746a56b43b`;
result SHA256 `9dbea92263f1cc23d1564fdb6685b4d19085491daf92fc602c4db4ac8393fc15`.
Existing Cicada and Agent City schemas compare equal before/after, and an added
read invokes the GET/null-body native envelope. The existing plugin owner must
reconcile this additive delta against the actual installed source before a
supported plugin update. Neither the application ZIP nor this source handoff
updates the installed plugin automatically. No plugin configuration, profile,
credentials, grants or running process was changed by these source checks.

`test_context_native_bridge.py` uses real disposable HTTP handlers and exact
owner delegation with a substituted pipe dispatcher. It covers authenticated
read/search, revision conflict, revoke, private-root metadata, rejected unknown
fields/types, foreign IDs, private filenames, no grant mutations, exact-query
one-use delegation, and no HTTP fallback. The hosted Windows native pipe
self-test additionally exercises real current-user pipe allowlisting for these
routes and denies mutation and route traversal. These are candidate checks;
installed tool discovery and end-to-end authorized reads remain required.

The frozen backend also retains the standalone entry point as
`AgentCityBackend.exe --internal-script context_mcp.py`; hosted candidate checks
verify its bundled parser with `--help` without opening an application or profile.
