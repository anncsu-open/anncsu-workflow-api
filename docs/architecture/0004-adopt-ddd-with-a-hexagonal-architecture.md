# 4. Adopt Domain-Driven Design with a hexagonal architecture

Date: 2026-06-06

## Status

Accepted

## Context

ADR 0002 made the Arazzo specification the canonical workflow contract; ADR 0003 proposed
a custom async executor to run it. Before implementing that executor, we need an agreed
architecture and a refactor of the existing codebase — otherwise execution logic,
transport/authentication, and the HTTP facade would entangle in an unstructured way.

The current code is a thin facade: `app/` holds only `config.py`, `main.py`,
`models/workflows.py` (flat I/O DTOs), and `routers/visualizer.py`. There is no
domain, application, executor, ports, or adapters layer; the `clients/`/`services/`
packages the README implies do not exist. The `interni` removal (decided earlier) is also
not yet propagated to the models and config.

The domain — management of ANNCSU addresses — has already been analysed in the design
notes: well-identified bounded contexts and two aggregates (Area di Circolazione/Odonimo
and Accesso/Civico, with Coordinate as a concern). A deliberate structure is needed so the
generic execution engine, the cross-cutting PDND authentication, and the public facade stay
separated and independently testable.

## Decision

We adopt **Domain-Driven Design** with a **hexagonal (ports & adapters) architecture**.

**Cardinal principle.** The domain model lives in the canonical Arazzo contract
(aggregates, the upsert saga, and cross-aggregate invariants expressed via
`steps`/`successCriteria`/`onSuccess`/`onFailure`/`x-executor`). The executor is a
**generic, domain-agnostic engine**: it has no ANNCSU rules hard-coded — it *reads*
`x-executor`. Invariants the SDK does not know (it only validates per-operation payloads)
live in the contract and are enforced by the engine.

**Context map.**
- **Gestione Anagrafica degli Indirizzi** — CORE. Declarative in the Arazzo spec, reflected
  in a minimal ubiquitous-language module.
- **Esecuzione Workflow** — generic subdomain: the executor engine.
- **Identità/Accesso PDND** — generic, cross-cutting: inside the SDK (GovWay/ModI/JWT).
- **Pubblicazione Contratto** — supporting: the FastAPI routes, I/O DTOs, and visualizer
  (the conformance gate, per ADR 0002).

**Package structure (hexagonal layers).**
- `app/domain/` — minimal ubiquitous language (value objects such as `Codcom`,
  `ProgrNazionale`, `ProgrCivico`, `TipoOperazione`); no rules already in the Arazzo.
- `app/application/` — `ApplicationService.run_workflow(workflow_id, inputs)`, returning a
  synchronous result (the `[BLOCK_REST]` model).
- `app/executor/` — the generic engine (spec loader, execution context, expression
  evaluator, step runner, coalesce, foreach).
- `app/ports/` — `WorkflowTransport` (async Protocol).
- `app/adapters/` — `AnncsuSdkTransport` (production) plus the response adapter; a
  MockTransport-based adapter for tests.
- `app/interfaces/` — the FastAPI routers and I/O DTOs (today's `models/` and `routers/`
  fold in here).

**Decisions settled here (from the DDD adoption plan).**
- **DDD-1**: adopt the hexagonal package names above, rather than keeping flat
  `models`/`routers`, because they make the bounded-context boundaries explicit.
- **DDD-2**: keep the Python domain layer **minimal** — value objects only. Aggregates and
  invariants stay in the Arazzo contract and the SDK; we do not re-implement them as Python
  domain objects.

**Out of scope / still open.** The transport-seam choice (D2 — typed per-operation SDK with
an `operationId` registry vs. SDK as a generic authenticated transport) and the other
executor specifics remain open; they are settled when ADR 0003 is implemented. This ADR
fixes the architecture and the boundaries, not the engine internals.

## Consequences

Easier:
- Clear bounded-context boundaries; the engine is reusable and driven entirely by the
  declarative contract, so new workflows need no per-workflow engine code.
- The application core is testable in isolation through the `WorkflowTransport` port
  (MockTransport), without reaching PDND.
- The facade stays thin and keeps its role as the OpenAPI conformance gate.

More difficult / accepted costs:
- A refactor of the existing code is required; the `interni` cleanup and DTO alignment to
  the consolidated spec (Phase A of the plan) are a prerequisite.
- The team must respect the cardinal rule — no domain logic in the engine — or the
  generic-executor design erodes.
- More packages and indirection than the current flat layout.
- The minimal-domain choice (DDD-2) means correctness of the cross-aggregate invariants
  depends on the Arazzo contract and the SDK; the contract's correctness becomes critical,
  and ADR 0003's executor must be built to honour `x-executor` faithfully.
