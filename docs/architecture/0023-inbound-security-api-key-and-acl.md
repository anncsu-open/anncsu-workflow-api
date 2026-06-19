# 23. Inbound security: API-KEY authentication + source-IP/hostname ACL

Date: 2026-06-18

## Status

Accepted

## Context

The facade has **no inbound authentication**: PDND auth is only *outbound* (toward
ANNCSU). The workflow routes are reachable by anyone who can hit the service (during
testing, via ngrok). For the Kubernetes deployment we must control *who* can call:
machine-to-machine (M2M) callers authenticate with an **API-KEY**, and that key is
accepted **only on the private ingress**.

## Decision

A single FastAPI security dependency guards the **workflow routes**
(`/anncsu/v1/workflows/*`). It enforces, **in order**:

1. **API-KEY (authentication).** A `APIKeyHeader` security scheme named **`X-API-KEY`**
   (so it appears in the OpenAPI `securitySchemes` and on the protected operations).
   The expected key is a **single** value from `.env` (`API_KEY`). Missing or wrong →
   **401**. The key value is **never logged** (redacted, ADR 0014).

2. **Source-IP ACL (authorization).** The caller IP is resolved from the **`X-Real-IP`**
   header (set by the k8s ingress), falling back to `request.client.host`. It must fall
   within an allowlist of **CIDR** ranges from `.env` (`ALLOWED_IPS`; a single IP is a
   `/32`, a subnet is `/N`, and `0.0.0.0/0` + `::/0` are the "any IP" wildcard).
   Outside the allowlist → **403**.

3. **Hostname ACL (authorization).** The called host `request.base_url.netloc` must be
   in an allowlist from `.env` (`ALLOWED_FQDN`). Not allowed → **403**. `netloc` is the
   `Host` header **verbatim, port included** (`X-Forwarded-Host` is not applied), so the
   allowlist must match it exactly: `localhost:8000` for local testing, the bare FQDN
   behind a k8s ingress (which strips 80/443). The rejection logs
   `access.host_not_allowed host=<value>`, the value to add.

All rejections are **RFC 7807 Problem** responses (`application/problem+json`,
ADR 0008), with the request-id correlation.

**Exempt** from all three checks: the probes (`/health`, `/ready`), the localized
docs/redoc/`openapi.json`, the root `/`, and the visualizer (`/workflows/ui`) — so
monitoring and discovery stay open. Scope is achieved by attaching the dependency to
the **workflow router only**; the other routers/mounts are naturally exempt.

**"API-KEY only on the private ingress"** is realized by the hostname ACL: the private
ingress has its own FQDN in `ALLOWED_FQDN`; the public ingress carries a different FQDN
and is rejected by check 3. No extra ingress header is required.

### Configuration (`Settings` / `.env`)

- `API_KEY: str` — the single expected key (**secret; never logged**).
- `ALLOWED_IPS: list[str]` — CIDR ranges (parsed with the stdlib `ipaddress`).
- `ALLOWED_FQDN: list[str]` — allowed called hostnames (host[:port]).

**Activation / unconfigured behaviour (fail-closed on the key, opt-in on the ACL):**

- `API_KEY` is **required**: if it is unset, the guard rejects every protected call
  (fail-closed) — the service refuses to serve workflows without a configured key.
- `ALLOWED_IPS` / `ALLOWED_FQDN` are **enforced when non-empty**; an empty list means
  "not restricted on that dimension". This keeps local dev / tests simple (set only
  `API_KEY`) while production sets all three. The private-ingress guarantee therefore
  depends on production populating `ALLOWED_FQDN`.

### Trust boundary

`X-Real-IP` is trusted **only because the k8s ingress sets it**. If the service were
reachable directly (e.g. ngrok in testing), a client could spoof `X-Real-IP`; the
hostname ACL (`ALLOWED_FQDN` = the private-ingress FQDN) is the mitigation. The service
must be exposed **only through the ingress** in production.

### Testing

The route tests do not exercise the guard, so they bypass it via
`app.dependency_overrides` (as they already do for the workflow service). Dedicated
tests cover the guard itself: valid key → 200; missing/wrong key → 401; IP outside
`ALLOWED_IPS` → 403; host outside `ALLOWED_FQDN` → 403; exempt paths reachable without
a key; the API-KEY never appears in logs.

## Consequences

- The workflow routes require an API-KEY and a network ACL; probes/docs stay open.
- The OpenAPI advertises the `X-API-KEY` security scheme on the protected operations.
- Defence in depth: authn (key) + two authz dimensions (IP, hostname), independently
  configurable.
- Fail-closed on the key; the IP/hostname restrictions are opt-in, so a production
  misconfiguration (empty `ALLOWED_FQDN`) weakens the private-ingress guarantee — to be
  caught by deployment config review.
