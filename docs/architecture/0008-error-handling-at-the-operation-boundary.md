# 8. Error handling at the operation boundary: exceptions vs Result types

Date: 2026-06-11

## Status

Accepted

(Settled by the Phase E implementation of the SDK transport adapter. Relates to ADR
0003's open question D3 — *response adapter* — and the route error handling of the
facade.)

## Context

We are considering whether to represent failures at the operation boundaries as **values**
(a Rust-style `Result[Ok, Err]`, e.g. `better-result-py`) instead of exceptions.

Current situation:

- **Domain failures are already data, not exceptions.** ANNCSU outcomes (`esito != "0"`,
  status codes) live in `Response.body` and are handled declaratively by the Arazzo
  `successCriteria`/`onSuccess`/`onFailure` (e.g. `esito == "23"`). That boundary is
  effectively already a "Result at the spec level".
- The **engine uses exceptions** (`StepFailedError`, `UnknownStepError`, `WorkflowError`).
- The FastAPI idiom favoured by the project skills is **exception handlers → RFC 7807**
  Problem Details.
- The genuine gap a Result type could address is the **infrastructure boundary** (Phase E):
  the transport adapter distinguishing "got an HTTP response" (even 4xx/5xx with an esito)
  from "the call itself failed" (network, 401/auth, timeout), and the application service →
  route mapping.

## Decision

**Exceptions, no Result type.** Phase E settled the boundary in the SDK transport
adapter (`app/adapters/anncsu/transport.py`) without introducing a `Result` dependency,
because the SDK's own error taxonomy already provides the discrimination a `Result`
would have encoded:

- **Any HTTP outcome becomes a `Response`.** A 200 returns the typed model, dumped to
  the wire shape; a documented 4xx/5xx is raised by the SDK as a *typed* `AnncsuBaseError`
  that always carries `status_code`/`raw_response`, and the adapter maps it back to a
  normalized `Response`. Either way the Arazzo `successCriteria`/`onFailure` keep
  deciding what the outcome *means* — domain failures (e.g. `esito == "23"`) stay
  spec-evaluated data, and no ANNCSU rule leaks into adapter code.
- **Failures of the call itself raise `TransportError`** (defined next to the port in
  `app/ports/transport.py`): network errors (`httpx.HTTPError`), `NoResponseError`,
  and PDND token refresh failures (`TokenRefreshError`). These never had an HTTP
  outcome the spec could evaluate; the facade will map them to RFC 7807 Problem
  Details via FastAPI exception handlers (Phase F).
- This settles ADR 0003's **D3 (response adapter)**: the wrapper over the SDK's typed
  Pydantic models is `Response(status_code, body, headers)`, produced from
  `model_dump(mode="json", by_alias=True)` on success and from the error's
  `raw_response` on documented failures.

The `Result` candidates (`returns`, `result`, `better-result-py`) were not needed: the
"got an HTTP response vs the call itself failed" distinction maps cleanly onto
return-vs-raise at a single, small boundary, and adding a second error paradigm (plus a
dependency under the Trivy/SBOM gate) bought nothing over it.

## Consequences

- One error model across the codebase: the engine keeps its exceptions, domain failures
  remain Arazzo data, and `TransportError` is the only boundary-crossing failure type
  the application service has to handle.
- No new dependency; nothing for the SBOM/Trivy gate.
- The route layer (Phase F) maps `TransportError` and the engine's `WorkflowError`
  family to RFC 7807 via exception handlers, the FastAPI-idiomatic path.
- If a future boundary genuinely needs value-based errors, the shortlist and the
  confinement rule recorded in the Context above still apply.
