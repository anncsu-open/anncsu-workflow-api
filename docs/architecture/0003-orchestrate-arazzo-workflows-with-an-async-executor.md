# 3. Orchestrate Arazzo workflows with an async executor

Date: 2026-06-04

## Status

Proposed

## Context

ADR 0002 establishes the Arazzo 1.0 spec as the canonical workflow contract, and
records that some orchestration cannot be expressed in pure Arazzo 1.0. Those gaps are
declared explicitly in `x-executor` blocks on the affected workflows:

- **Output coalescing across alternative branches.** In
  `verifica-e-crea-indirizzo-completo`, a value such as `progressivo_nazionale` is
  produced by *either* the `cerca-odonimo` branch *or* the `crea-odonimo` branch,
  depending on which `goto`/fall-through path ran. Arazzo 1.0 cannot express
  "take the first non-null of these". The spec declares the resolution order under
  `x-executor.coalesce`.
- **For-each iteration.** In `sopprimi-odonimo-completo`, the ANNCSU invariant is that
  an odonimo cannot be suppressed while it has residual accessi (error 320 / `esito == "23"`).
  All accessi listed by `elenca-accessi` must therefore be suppressed *before*
  `sopprimi-odonimo`. Arazzo 1.0 has no for-each, so `x-executor.foreach` declares that
  the executor iterates `lista_accessi`, invoking the reusable `sopprimi-accesso`
  workflow per item, and must abort `sopprimi-odonimo` if any single suppression fails.

These workflows also make several outbound HTTP calls to ANNCSU through PDND, each
incurring authentication (JWT bearer + `Agid-JWT-Signature` + `Agid-JWT-TrackingEvidence`)
and subject to PDND rate limiting. The service is FastAPI/ASGI, which is async-native.

A ready-made runner (e.g. arazzo-runner) was rejected in ADR 0002 because it couples
execution to synchronous semantics and does not understand our `x-executor` extension.
We need an executor that (a) honours the `x-executor` contract and (b) fits an async
I/O-bound service.

## Decision

We will implement a **custom asynchronous executor** that consumes the Arazzo spec and
its `x-executor` extension, rather than adopt an off-the-shelf synchronous runner.

The executor is responsible for:
- walking a workflow's sequential steps and evaluating `successCriteria`,
  `onSuccess`/`onFailure` `criteria`, and `goto`/`end` actions;
- resolving runtime expressions (`$inputs`, `$steps.*.outputs`, `$response.body`, …)
  and binding `operationId`s to the ANNCSU OpenAPI sources;
- applying `x-executor.coalesce` to produce workflow outputs from whichever alternative
  branch actually executed (first non-null in the declared order);
- applying `x-executor.foreach`: iterating the declared collection and invoking the
  named reusable workflow per element at the declared position (`before:`), and stopping
  the parent workflow if any iteration fails;
- performing outbound calls asynchronously (`async`/`await` over an async HTTP client),
  so concurrent ANNCSU requests and PDND auth do not block the event loop.

The executor runs **inside** the async FastAPI service. The orchestration is async, but
each workflow endpoint still returns a **synchronous result** to the caller (the API
waits for the workflow to complete and returns its coalesced outputs) — there is no
deferred job/callback model at this stage.

## Consequences

Easier:
- The full orchestration story — branching (Arazzo) plus coalesce/for-each (`x-executor`)
  — lives in one component driven by the canonical contract, instead of being
  reimplemented per endpoint.
- Async I/O matches the FastAPI runtime and lets independent ANNCSU calls overlap,
  improving latency under PDND rate limits.
- `sopprimi-accesso` is a reusable workflow invoked by the for-each, so the
  accesso-suppression logic exists once.
- New workflows that need coalesce/for-each are added declaratively in the spec; the
  executor needs no per-workflow code.

More difficult / accepted costs:
- We own and maintain a non-trivial interpreter: expression evaluation, criteria,
  `goto`/`end` flow, coalesce, and for-each must all be implemented and tested. This is
  the largest open follow-up from the Arazzo consolidation work.
- `x-executor` is a bespoke extension; its semantics are defined only by this executor
  and these ADRs, not by the Arazzo standard. Spec and executor must evolve together.
- The synchronous request/response model means long workflows (e.g. suppressing an
  odonimo with many accessi) hold the HTTP connection open; a future async-job model may
  be needed and would be a separate decision.
- The reject-vs-cascade behaviour of odonimo suppression on the server side is still
  **to be confirmed in SOGEI validation**. Explicit per-accesso suppression is robust
  under both hypotheses, but the executor's error handling around `esito == "23"` may
  need revisiting once confirmed.
