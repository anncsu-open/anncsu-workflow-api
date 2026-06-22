# 24. Lazy-build PDND auth failures are TransportError, not unhandled 500s

Date: 2026-06-22

## Status

Accepted (refines ADR 0008; relates to ADR 0017)

## Context

A k8s run surfaced failures never seen locally: every `aggiorna-accesso-da-progressivo`
request returned an **unhandled ASGI 500 with a full stack trace** instead of an
RFC 7807 Problem. The traceback is identical for all of them:

```
engine._execute_step → transport.dispatch → manager.client(source)
  → builders[source]()                       # lazy build (ADR 0017)
  → audience_resolver(auth_manager.get_access_token())
  → anncsu.common.pdnd_token.get_access_token
  → TokenResponseError: 015-0008 - Unable to generate a token for the given request
```

The root cause of the 015-0008 itself is environmental — the **accessi** source's PDND
purpose/agreement is misconfigured or inactive in that environment (consultazione and
odonimi built fine; accessi/coordinate never did). That is fixed in the deployment, not
here.

The defect *here* is the handling. ADR 0008 says "failures of the call itself raise
`TransportError`" and lists `httpx.HTTPError`, `NoResponseError`, and the PDND token
**refresh** failure (`TokenRefreshError`). But the SDK client is built **lazily on first
use** (ADR 0017): the first dispatch to a source fetches a voucher and derives the
e-service URL. Two failure modes of that build were never added to the boundary:

- **`TokenError`** (SDK base; covers `TokenResponseError` and `TokenRequestError`) — the
  PDND token endpoint rejects the assertion at build time (the observed `015-0008`). This
  is distinct from `TokenRefreshError`, which the SDK raises for a *mid-call* refresh.
- **`AudienceDiscoveryError`** (ours, raised by the builder when the voucher carries no
  audience, ADR 0017).

Neither is an `AnncsuBaseError` (no HTTP outcome, no `status_code`), so neither maps to a
`Response`; and neither was in the `dispatch` `except` clause. They escaped the transport
adapter, sailed past the engine's `except TransportError` and the RFC 7807 exception
handlers, and reached uvicorn as a raw 500 — leaking the stack trace and giving the caller
a body that is not a Problem.

## Decision

**Wrap lazy-build PDND auth failures into `TransportError` at the transport boundary.**
`AnncsuSdkTransport.dispatch` already normalizes "the call itself failed" into
`TransportError`; extend that same `except` clause to also catch:

- `anncsu.common.pdnd_token.TokenError` — the SDK base for token request/response
  failures, so `TokenResponseError` (`015-0008`) and `TokenRequestError` are both covered;
- `app.adapters.anncsu.auth.AudienceDiscoveryError` — the build's own
  no-audience-in-voucher failure.

Both are "failures below the Arazzo contract" exactly like the network/refresh cases: no
HTTP outcome ever reached the executor, so there is nothing for `successCriteria`/
`onFailure` to evaluate. Wrapping them preserves the original as `__cause__`. The engine
and the error handlers are unchanged: a `TransportError` already maps to a **502 Problem**
(ADR 0008), carries the partial per-step trace (ADR 0022), and is logged as an `error`
(ADR 0014) with the correlation id — no stack trace to the caller.

## Consequences

- A misconfigured (or transiently unavailable) PDND source now yields a clean **502
  Problem Details** with a partial trace, not a raw 500 — consistent with every other
  upstream failure, and diagnosable from the structured logs without leaking internals.
- The fix is one boundary, two added exception types; ADR 0008's "single small boundary"
  invariant holds — `TransportError` stays the only boundary-crossing failure type.
- The boundary now covers the **whole** PDND auth lifecycle: build-time token generation
  and audience discovery (this ADR) plus mid-call refresh (ADR 0008).
- The environmental cause of `015-0008` (the accessi purpose/agreement in that
  environment) is out of scope here and handled in the deployment configuration.
