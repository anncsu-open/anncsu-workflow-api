# 17. Discover ANNCSU server URLs from the PDND voucher

Date: 2026-06-15

## Status

Accepted (refines ADR 0015)

## Context

ADR 0015 wired the SDK clients with **hardcoded** per-source server URLs
(`ANNCSU_*_URL` settings, switched by `use_validation_env`). Operating the service
against the collaudo (UAT) environment surfaced that this is fragile and
incomplete:

- the validation consultazione URL pointed at a host that does not exist
  (`modipa-val.agenziaentrate.gov.it`, NXDOMAIN — the real host is
  `…agenziaentrate.it`);
- `accessi`/`coordinate` have **no** validation URL, so in validation mode they
  target **production** — wrong for collaudo credentials;
- the collaudo endpoints serve a **self-signed TLS certificate**, which the SDK's
  default HTTP client rejects.

The SDK CLI avoids the URL problem entirely: it derives each e-service's real base
URL from the PDND **voucher's `aud` claim** (`extract_voucher_audience`), so the
URL always matches the environment and purpose the voucher was minted for. For the
certificate it exposes a `--no-verify-ssl` switch.

## Decision

### 1. Server URL from the voucher audience

Drop the hardcoded `ANNCSU_*_URL` settings (and the `*_val_url` switching). Each
source's SDK client takes `server_url = extract_voucher_audience(voucher)` — the
authoritative per-purpose e-service URL carried by the voucher. The environment
(UAT vs production) is still selected by the **token endpoint**
(`use_validation_env`), and the voucher's `aud` follows from it. There is nothing
left to keep in sync by hand.

### 2. Lazy per-source client build, off the event loop

`AnncsuClientManager` builds each SDK client **on first use** (`client(source)`):
it fetches the voucher (`PDNDAuthManager.get_access_token`), reads its audience,
and constructs the client with that URL, caching it. This preserves ADR 0015's
posture that startup performs no PDND I/O — clients and tokens stay lazy; the first
dispatch (or `/ready`) triggers discovery, and the manager caches the voucher
(refresh stays automatic).

Because the discovery does a synchronous PDND call, the transport is restructured
so the client is resolved **inside** the `asyncio.to_thread` call under the
per-source lock (today it is resolved on the event loop before the lock); this
keeps the blocking voucher fetch off the event loop and serialized per source
(anncsu-sdk#35).

### 3. TLS verification toggle

Add `verify_ssl: bool = True`. The SDK clients are built with
`httpx.Client(verify=verify_ssl)`. Collaudo (self-signed certificate) sets
`VERIFY_SSL=false`; production keeps verification on.

## Operational notes (avoid surprises)

- **Cold first request per source.** The first dispatch to a source (or the first
  `/ready`) pays a voucher fetch + URL discovery; subsequent requests reuse the
  cached client. `/ready` can be used as a warm-up. This first call is therefore
  slower and is the point where an auth/URL misconfiguration first shows up.
- **The discovered URL is fixed for the process lifetime.** The client is cached
  once built; the manager keeps refreshing the *voucher* (token), but the *URL* is
  not re-derived. If an e-service URL changes, restart the service to re-discover.
- **The voucher fetch runs in the worker thread, under the per-source lock.** The
  transport resolves the client inside `asyncio.to_thread`, so the blocking call
  never runs on the event loop, and two concurrent dispatches to the same source
  build the client once (the second waits on the lock and reuses the cache).
- **Failures surface as 502/503, not a startup crash.** A source whose voucher or
  audience cannot be obtained fails that dispatch (502) and is reported not-ready
  by `/ready` (503); startup itself does no PDND I/O.
- **Logging (ADR 0014).** Each lazy build logs a structured event with the source
  and the discovered server URL (`client.built`, INFO — one line per source per
  process), so operators can confirm which environment/URL is actually in use; the
  URL is not a secret. A discovery failure logs at `error` with the source.

## Consequences

- The hardcoded-URL bugs (wrong/missing validation URLs) disappear; URLs always
  match the voucher's environment and purpose. `Settings` loses the `ANNCSU_*_URL`
  fields (and `server_urls_from_settings`); `use_validation_env` now drives only the
  token endpoint.
- The service works end-to-end against collaudo (correct URLs from the voucher +
  the `verify_ssl` toggle for the self-signed certificate).
- A source's first request (or `/ready`) performs the voucher fetch + URL
  discovery; later requests reuse the cached voucher/client. Startup stays
  PDND-independent (ADR 0015 preserved); a source whose voucher cannot be obtained
  fails its dispatch (502) / readiness (503) — the same failure surface as before.
- The transport resolves the client inside the worker thread, so the (now
  network-bearing) client build never blocks the event loop.
- Tests inject fake auth managers / a fake voucher-audience resolver, so no real
  PDND credentials or network are needed; a regression exercises the real SDK
  against a fake server to pin the discovered-URL wiring.
