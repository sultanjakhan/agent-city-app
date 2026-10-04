# Agent City encrypted activity relay

This is the existing Agent City relay, exported into the application repository
so clients and server can be maintained together. No additional GitHub repository
or deployed service is needed. The client is `../cloud_sync.py`.

The design follows Cicada: local-first data, end-to-end encrypted transport,
per-device identity, durable acknowledgements, retry and separate credentials.
This activity snapshot protocol is intentionally distinct from Cicada's record
change log. It currently exchanges agent reports only. Rules, settings and skill
files require their own validated record adapter and conflict/deletion rules;
copying Cicada's Rust implementation into Python would not provide that adapter.

The Worker stores up to eight encrypted snapshots, one per enrolled device.
It never receives the encryption key or task titles/content. A device may update
only its own snapshot using monotonic revisions; repeating the same revision and
ciphertext is idempotent. Windows clients protect connection credentials using
DPAPI; macOS clients use Keychain. Never clone a device identity onto a second
simultaneously running device. Client local-only mode disables this integration.

## Free deployment

The configuration uses **SQLite Durable Objects**, supported on Workers Free.
There is no paid dependency or required custom domain. Use a Workers Free account;
this configuration does not change an account's subscription or billing plan.
Free usage has quotas; on quota exhaustion Cloudflare rejects operations rather
than charging Free accounts. Clients must keep their local data and pending
encrypted snapshot until the next successful exchange. Account quotas are shared
with other Workers; this repository is not evidence of an account's current plan.

See the current [official pricing](https://developers.cloudflare.com/durable-objects/platform/pricing/).
For a small number of personal devices, capped snapshots and infrequent exchange
are a reasonable fit for those quotas. This is an estimate, not a usage guarantee.

## Maintainer

Run `npm ci --ignore-scripts`, `npm test`, then `npm run check` (dry run).
For existing tooling, tests accept `AGENT_CITY_MINIFLARE_MODULE` as a local module
URL, allowing reuse without another dependency installation.

Deploy only after verifying the selected account is Workers Free and the
existing `agent-city-sync-v1` service identity. Do not overwrite Cicada's relay,
namespace or secrets. `DEVICE_HASHES` is an external secret containing the mapping
SHA256(token) to device ID. Profiles and secrets stay outside Git and release ZIPs.
Do not reprovision an existing group merely to obtain a new pairing file.

The endpoint is `https://agent-city-sync-v1.<account>.workers.dev` and the profile
is `agent-city-activity-v1`. Each device receives a distinct token and identity,
and devices in a group share the encryption key through a private pairing channel.
The backend uses AES-256-GCM with profile/endpoint/device/revision as authenticated
data, and retains pending ciphertext for safe retries after a lost ACK.

Exporting and locally testing this source is not proof of a live deployment,
an enabled client connection or physical Mac/PC synchronization.
