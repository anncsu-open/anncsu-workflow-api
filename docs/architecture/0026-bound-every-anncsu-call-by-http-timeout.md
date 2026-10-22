# 26. Bound every ANNCSU call by HTTP_TIMEOUT and derive the dispatch backstop from it

Date: 2026-10-22

## Status

Accepted (refines ADR 0017; GitHub issue #26)

## Context

ADR 0017 bounds each dispatch twice. The HTTP client timeout is the inner bound, and
`asyncio.wait_for(..., DISPATCH_TIMEOUT_SECONDS)` is the outer backstop that releases the
per-source lock. That ADR assumed the SDK's 5s HTTP timeout. The timeout later became the
`HTTP_TIMEOUT` setting (default 20s), set on the `httpx.Client` handed to the SDK.

In production an odonimo update timed out after 20s, and raising `HTTP_TIMEOUT` to 30
only moved the failure to the backstop. A local mock e-service that never answers showed
why:

- Unless `timeout_ms` is set, anncsu-sdk sends every request with `timeout=None`, and
  httpx reads an explicit `None` as "no timeout". The client timeout never applied to
  reads.
- ModI-signed writes were bounded as a side effect: the ModI hook rebuilds the request
  without its extensions, so `client.send` falls back to the client timeout.
- The backstop was a fixed 30s, so an `HTTP_TIMEOUT` of 30s or more had no effect. A read
  that hit the backstop kept its worker thread and connection open after the 502.

## Decision

- `make_client_builder` passes `timeout_ms = HTTP_TIMEOUT * 1000` to every SDK client, so
  reads and writes carry the timeout explicitly. The `httpx.Client` keeps the same
  timeout, which applies to the requests the ModI hook rebuilds.
- The backstop is derived from the setting: `build_workflow_service` gives the transport
  `HTTP_TIMEOUT + DISPATCH_MARGIN_SECONDS` (10s). The margin covers what httpx does not
  bound, mainly the voucher fetch and ModI signing of a cold first call, so the HTTP
  timeout normally fires first. `AnncsuSdkTransport` has no default backstop; the caller
  passes one.
- `HTTP_TIMEOUT` stays the single knob. With the default of 20s the backstop is 30s, as
  before.

## Consequences

- An upstream that does not answer fails at `HTTP_TIMEOUT` with `failed before an HTTP
  outcome: timed out`, for reads and writes alike, and the connection is closed. The
  `timed out after Ns` message now means something outside the HTTP call hung, such as
  the voucher fetch.
- Reads that used to run until the 30s backstop now stop at `HTTP_TIMEOUT`, 20s by
  default.
- A long `HTTP_TIMEOUT` needs matching timeouts outside this repo: the ingress read
  timeout (nginx-ingress defaults to 60s) and the callers' timeouts. Both must cover the
  whole workflow, which chains several calls.
- A slow call holds the per-source lock for up to `HTTP_TIMEOUT` plus the margin, and the
  wait for the lock itself is not bounded. Long timeouts slow down bulk runs against the
  same source.
- The regression tests check the behaviour against a silent local upstream. The previous
  test only checked the timeout declared on the client, which is how this bug went
  unnoticed.
- A write that times out may still have been applied upstream. This decision does not
  change that; callers should check with a read before retrying.
