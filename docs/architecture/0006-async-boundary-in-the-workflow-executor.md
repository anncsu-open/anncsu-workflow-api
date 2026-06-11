# 6. Async boundary in the workflow executor

Date: 2026-06-11

## Status

Accepted

(Refines ADR 0003 — *Orchestrate Arazzo workflows with an async executor* — and builds
on the `WorkflowTransport` port of ADR 0004.)

## Context

ADR 0003 established a custom **async** executor. While implementing it (the generic
engine, then `x-executor.coalesce`/`foreach`), a recurring question surfaced: *which parts
of the executor must be `async`, and which should stay synchronous?*

The executor mixes two very different kinds of work:

- **I/O orchestration** — dispatching an operation through the transport, and (for
  `foreach`) invoking sub-workflows that themselves dispatch operations. This reaches the
  network (ANNCSU through PDND).
- **Pure evaluation** — resolving runtime expressions (`$inputs`, `$steps.*.outputs`,
  `$response.*`), evaluating `successCriteria` and `onSuccess`/`onFailure` criteria,
  selecting actions, resolving `goto` targets, extracting step/workflow outputs, and
  `x-executor.coalesce`. All of this reads data already collected in the execution context;
  it performs no I/O.

Making *everything* `async` (cargo-cult) or keeping *everything* sync (blocking the event
loop on network calls) would both be wrong. We need an explicit rule for where the async
boundary sits.

## Decision

**Async is confined to the I/O boundary and the call chain that awaits it; everything
pure stays synchronous.**

- The `WorkflowTransport.dispatch` port is `async`. The chain that reaches it is `async`:
  `WorkflowExecutor.run` → `_execute_step` → `await transport.dispatch(...)`. The `foreach`
  orchestration (`_run_foreach`/`_maybe_run_foreach`) is `async` because it awaits a
  sub-workflow run per item.
- The pure, I/O-free logic is **synchronous**: the runtime-expression evaluator,
  criteria evaluation, action selection, `goto` resolution, output extraction, and
  `x-executor.coalesce`. These take the already-populated context as input and return a
  value. Declaring them `async def` without an `await` would add overhead and falsely
  imply concurrency.
- **`async` ≠ parallel.** Here `async` means *not blocking the event loop* — the transport
  adapter performs non-blocking I/O (the ANNCSU SDK's `_async` methods over an
  `httpx.AsyncClient`). It does **not** mean operations run concurrently. In particular,
  `foreach` is **sequential and fail-fast** (decision D5): the ANNCSU invariant requires all
  accessi to be suppressed *before* the odonimo, in a deterministic order, so sub-workflows
  are `await`ed one at a time — never `asyncio.gather`-ed.
- The non-blocking guarantee ultimately depends on the transport adapter (introduced later)
  calling the SDK's async methods. The SDK's current sync-only token refresh is tracked as
  `anncsu-open/anncsu-sdk#35` and carried, until fixed, behind an `asyncio.to_thread` seam
  in the adapter — without leaking into the engine.

## Consequences

Easier:
- A small, auditable async surface (only the I/O chain) and a large pure core that is
  trivially unit-testable without an event loop or mocks for async.
- Clear guidance for contributors: add `async`/`await` only where you await I/O; never on
  evaluation helpers.

More difficult / accepted costs:
- Contributors must internalise the rule; an accidental blocking call inside an `async`
  path (or a needless `async def` on a pure helper) is a review item, not a compiler error.
- `foreach` being sequential bounds throughput for large accesso lists — accepted, because
  the domain invariant requires ordered, all-or-nothing suppression before the odonimo.
- The real non-blocking behaviour is only realised once the transport adapter uses the
  SDK's async methods (depends on `anncsu-sdk#35`); the engine merely exposes the correct
  async seam.
