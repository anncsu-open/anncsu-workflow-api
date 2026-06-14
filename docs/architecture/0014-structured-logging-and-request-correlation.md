# 14. Structured logging with request correlation

Date: 2026-06-14

## Status

Accepted

**structlog** is adopted (the comparison with loguru and the rejected stdlib
baseline is kept below as the rationale).

## Context

The service has **no logging at all** today: no logger, no library, no
configuration. Concrete consequences:

- The RFC 7807 exception handlers (ADR 0008) return `422`/`500`/`502` to the
  client but write **nothing server-side** — an upstream PDND failure leaves no
  diagnostic trace.
- The ANNCSU SDK accepts a `debug_logger` we never pass, so the outbound calls
  to PDND (auth, the per-API requests) are silent.
- A workflow runs multiple steps and outbound calls; there is **no correlation
  id**, so a single run cannot be reconstructed end-to-end.

For a service orchestrating multi-step sagas over PDND (token refresh #35, rate
limits, `esito`/error 320, coalesce/foreach branching) this is a material
observability gap.

Requirements for the logging system:

1. **Structured output** (JSON in production, human-readable in dev), so logs are
   aggregatable.
2. **Request correlation**: one id per request, propagated through the async
   engine steps and the outbound SDK calls, and surfaced on the Problem
   responses.
3. **Secret/PII redaction**: never log PDND tokens, JWT bearer,
   `Agid-JWT-Signature`/assertions; treat payloads (addresses, `codcom`) as
   sensitive — identifiers at INFO, full bodies only at DEBUG with redaction.
4. **Integrate stdlib/uvicorn loggers** so framework logs share the same format.
5. **Config-driven** level/format (`Settings`), wired in the app lifespan.
6. Respect the project gates: **ty** (typed), **Trivy/SBOM** (dependency weight),
   no C extensions.

The intent is to adopt **structlog or loguru**, not hand-rolled stdlib logging.

## Decision

Adopt **structured logging behind a thin `app/logging.py` setup module**, with a
correlation-id middleware and instrumentation at three layers (route, executor,
transport) plus the exception handlers. Logged via one of:

### Option A — structlog (recommended)

- **Structured-first**: a processor pipeline renders JSON (prod) or console
  (dev); the correlation id is bound once via `contextvars`
  (`structlog.contextvars.bind_contextvars`) and flows through async steps with
  no manual threading.
- **stdlib integration by design**: `ProcessorFormatter` routes uvicorn/stdlib
  records through the same pipeline, so all logs share one format.
- **Redaction as a processor**: a single central processor drops/masks sensitive
  keys — the natural place for the secret/PII rule.
- **Typing**: ships types; friendly to the `ty` gate.
- Cost: more explicit setup than loguru; the processor model has a small learning
  curve.

### Option B — loguru

- **Ergonomics**: one `logger`, near-zero config, excellent tracebacks; JSON via
  `serialize=True`; async context via `logger.contextualize(...)`.
- Costs for this codebase: it is **not** stdlib-based, so capturing
  uvicorn/stdlib logs needs an `InterceptHandler` shim; the single dynamic
  `logger` object is **weaker under `ty`** (chained `bind`/`contextualize` calls
  type loosely); redaction is done via a `patch`/filter rather than a first-class
  pipeline.

### Decision: structlog

**structlog is adopted.** For an async FastAPI service with a correlation id
flowing through workflow steps, a structured-first pipeline, central redaction,
native stdlib/uvicorn integration, and clean `ty` typing outweigh loguru's
ergonomic edge. loguru was the runner-up (better DX) but loses on stdlib/uvicorn
integration and `ty` typing.

(stdlib `logging` + a JSON formatter was the baseline; rejected per the project's
intent to use a structured-logging library rather than maintain formatter glue.)

### Design (independent of the library chosen)

- `app/logging.py`: `configure_logging(settings)` called from the app lifespan;
  level + format (`json`/`console`) from `Settings` (`log_level`, `log_format`).
- **Correlation-id middleware**: read an inbound `X-Request-ID` or generate one;
  bind it to the logging context; echo it on the response header and as an
  extension member of the Problem body.
- **Instrumentation**:
  - route/app: one event per request — workflow id, outcome, duration, status.
  - executor: per-step event — `operationId`, succeeded, `esito`, branch taken,
    coalesce/foreach decisions (INFO/DEBUG).
  - transport: per dispatch — `operationId`, `status_code`, duration; and the
    exception handlers **log** the failure they map to a 5xx/422.
- **Redaction**: a central processor masks sensitive keys
  (`authorization`/`token`/`jwt`/`assertion`/`secret`/`password`/`pdnd_client`);
  tokens/JWT are never logged. Request payloads are **not** logged at all — the
  instrumentation records identifiers (`operationId`, `status_code`, request id),
  not bodies.
- **SDK `debug_logger` left unwired (deliberate)**: the central processor redacts
  by *key*, but the SDK's `debug_logger` emits free-text request/response dumps
  whose message strings would carry bearer tokens / `Agid-JWT-Signature` outside
  any key the processor can mask. The structured `transport.dispatch` event
  already gives the per-call observability (operation, status, duration) safely,
  so the SDK debug hook stays off rather than risk a secret leak. Wiring it later
  would require message-level scrubbing first.

## Consequences

- Failures and multi-step runs become traceable end-to-end via the correlation
  id; the silent-5xx problem is closed.
- One new runtime dependency (structlog or loguru), pure-Python, under the
  SBOM/Trivy gate.
- A logging seam exists for a later metrics/tracing phase (OpenTelemetry/Sentry),
  which is **out of scope here** — this ADR is logging only.
- Tests assert behaviour with `caplog`/captured output (e.g. a transport failure
  logs an error carrying the correlation id), not log wording.
