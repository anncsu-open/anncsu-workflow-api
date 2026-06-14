# 15. PDND authentication, configuration alignment, and readiness

Date: 2026-06-15

## Status

Accepted

## Context

The service has never authenticated to PDND. Two concrete gaps:

- **Dead configuration.** `Settings` declares a PDND/JWT/audit block
  (`pdnd_client_id`, `pdnd_client_secret`, `pdnd_token_url`, `pdnd_audience`,
  `jwt_private_key_path`, `jwt_algorithm`, `user_id`, `user_location`, `loa`) that
  is **never passed to the SDK** — `AnncsuClientManager.from_settings` builds each
  sub-SDK client with only `server_url`. The fields load from `.env` and go
  nowhere.
- **No auth wiring.** No `PDNDAuthManager`, no `Security`, no token hook is
  created anywhere in `app/`. A real dispatch to PDND would fail with `401`.

Meanwhile the SDK already owns a complete, validated auth contract:

- `anncsu.common.config.ClientAssertionSettings` (pydantic-settings,
  `env_prefix="PDND_"`): `PDND_KID/ISSUER/SUBJECT/AUDIENCE`, one
  `PDND_PURPOSE_ID_*` per API (all six must be present, may be empty),
  `PDND_PRIVATE_KEY`/`PDND_KEY_PATH`, and ModI fields
  (`PDND_MODI_USER_ID/USER_LOCATION/LOA`, `PDND_MODI_KID`,
  `PDND_MODI_PRIVATE_KEY`/`PDND_MODI_KEY_PATH`). Its model validators fail fast on
  a missing key source or missing purpose ids.
- `anncsu.common.auth.PDNDAuthManager` (one instance **per API type**, because
  each API uses a different `purpose_id`): caches the client assertion and the
  access token and refreshes them before expiry. It exposes `get_access_token()`,
  TTL accessors, and is consumed by the SDK clients through a **security-provider
  callable** that Speakeasy invokes before each request, so token refresh is
  automatic.
- Write APIs (accessi, odonimi, coordinate) additionally require ModI headers
  (`Agid-JWT-Signature`, INTEGRITY_REST_02 / AUDIT_REST_02): the SDK registers a
  ModI hook (`register_modi_hook` + `ModIConfig` + `AuditContext`) on the client,
  with `modi_audience == server_url`.

Finally, configuration is a module-level singleton (`settings = Settings()`); there
is **no application lifespan**, and `/health` returns a static `{"status": "ok"}`
with no dependency on the only thing that can actually fail at runtime — PDND auth.

## Decision

### 1. Align configuration with the SDK env contract

`Settings` keeps only application concerns — `app_name`, `app_version`, `debug`,
`log_level`/`log_format` (ADR 0014), the four server URLs (+ the two validation
URLs), `use_validation_env`, and the HTTP timeout/retries. The dead PDND/JWT/audit
fields are **removed**. PDND credentials are owned by the SDK's
`ClientAssertionSettings`, loaded from the **same** `.env`. This makes the env the
single source of truth and lets the SDK's validators reject a misconfigured
deployment at startup.

The PDND token endpoint is derived from `use_validation_env` (UAT when validation,
production otherwise) via a small `resolve_token_endpoint` helper, mirroring the
SDK's own UAT/production split.

### 2. Build authentication in an application lifespan

A FastAPI `lifespan` builds, once:

- the `ClientAssertionSettings` (fail-fast on missing PDND config);
- one `PDNDAuthManager` per source (`pa`, `accessi`, `odonimi`, `coordinate`),
  built **eagerly** (validates purpose ids / key source) but **without fetching
  tokens** — tokens are obtained **lazily** by the security-provider callable on
  the first request and refreshed automatically thereafter;
- the authenticated `AnncsuClientManager`: each client gets a
  `security=lambda: <ApiSecurity>(bearer=manager.get_access_token())` provider;
  the three write clients additionally get a ModI hook when `PDND_MODI_*` is
  configured (and a logged warning, then degraded operation, when it is not —
  matching the SDK CLI).

The manager is stored on `app.state`; the route dependency
(`get_workflow_service`) resolves it from there instead of constructing a default
per request. The per-source `asyncio.Lock` and the `asyncio.to_thread` seam in the
transport are unchanged (the SDK token refresh is sync-only, anncsu-sdk#35).

### 3. Liveness `/health` + readiness `/ready`

`/health` stays a cheap **liveness** probe (process up, no external dependency) so
an orchestrator never restarts the pod over a transient PDND blip. A new `/ready`
**readiness** probe exercises the auth engine across all four sources using the
manager's **cached token + TTL** (it refreshes only when near expiry, never forcing
a fresh login per hit), run via `asyncio.to_thread` under the per-source lock. It
returns `200` with a per-source status (configured / token TTL) when every required
source can authenticate, and `503` otherwise.

### 4. Token lifecycle: in-memory, no session file

Each `PDNDAuthManager` caches its client assertion and access token **in memory on
the instance**, and the instance lives on `app.state` for the whole process
lifetime. Expiry is **intrinsic to the token**: the manager reads the JWT `exp`
claim and refreshes the voucher 60 s before it expires (the assertion one day
before). Because the SDK invokes the security-provider callable **before every
request**, refresh is automatic and lazy — no background scheduler, no manual
expiry bookkeeping. `/ready` reports TTLs straight from this in-memory state.

`session_persistence` is **off**. It only governs an on-disk session file
(`~/.anncsu/session_*.json`) for **cross-process** reuse — the CLI's model, where
each invocation is a fresh process. A long-running server keeps the cache in
memory, so the file would only save a cheap re-mint on restart while adding
footguns: write races on a shared volume and the stale-session-on-env-switch class
of bug (the `015-0008` failure). Rejected for the server.

**More than one replica/worker** is safe with in-memory tokens: each replica
authenticates independently — its own assertion (unique `jti`, so no PDND replay
collision) and its own voucher, and PDND permits a client to hold concurrent
vouchers. There is no shared mutable state, hence no cross-replica contention, and
readiness is naturally per-replica (Kubernetes probes each pod — the correct
model). Sharing tokens across replicas would need an **external cache (e.g.
Redis)**; it is deferred because it is unnecessary for correctness and would only
marginally reduce the (already tiny) number of vouchers minted.

## Consequences

- The service can authenticate and make real PDND calls; the silent-401 gap is
  closed. `/ready` gives an operational auth signal without coupling liveness to an
  external dependency or hammering the token endpoint.
- One env contract (the SDK's `PDND_*`), validated at startup; the divergent,
  dead `Settings` fields are gone. `.env`/README document the `PDND_*` keys,
  including all six `PDND_PURPOSE_ID_*` (empty allowed for the unused APIs) and the
  `PDND_MODI_*` block required by the write APIs in production.
- Configuration and the auth lifecycle now live in the lifespan (not a module
  singleton); routes receive the client manager by dependency injection (ADR 0004).
- Secrets stay out of logs (ADR 0014): the redaction key set is extended to cover
  `private_key`, and auth objects are never logged.
- Tests inject fake auth managers / client managers, so no real PDND credentials
  are needed in CI.
- Tokens are in-memory per process and the design scales horizontally without a
  shared store (see *Token lifecycle*); an external token cache (Redis) is a future
  option, not a requirement.
- Out of scope: the `interni` API (not exposed by this service) and
  `coordinate_bulk`; their purpose ids stay empty in `.env`.
