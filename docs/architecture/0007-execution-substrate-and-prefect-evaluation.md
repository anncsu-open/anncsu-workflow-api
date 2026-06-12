# 7. Execution substrate: in-process executor now, Prefect under evaluation for async/bulk

Date: 2026-06-11

## Status

Proposed

(Forward-looking analysis. Refines the execution side of ADR 0003 — *async executor* —
and ADR 0006 — *async boundary*; does not change the Arazzo contract of ADR 0002.)

## Context

We may evolve the service into a managed *workflow manager*. Two questions came up:

1. Should we adopt a state-machine library (`pytransitions/transitions`) to manage each
   workflow run's state?
2. Does it make sense in view of a possible move to **Prefect** as the orchestration
   platform?

Current model: the workflow control flow lives declaratively in the canonical **Arazzo
spec** (ADR 0002) and is executed by a **generic async engine** (ADR 0003/0006). A run's
state is the ephemeral, in-memory `ExecutionContext` + `WorkflowRun`; the API is
**synchronous, in-band** (`[BLOCK_REST]`, ADR 0003) — there is no persistence, resume, or
scheduling today.

## Decision

**Reject `pytransitions/transitions`.** It would re-encode in Python the control flow
already declared in Arazzo and executed by the generic engine — duplicating logic and
pulling domain flow back into code, against ADR 0004's cardinal principle. It does not
model `x-executor` coalesce/foreach/sub-workflow invocation, and it provides no durability
(it is an in-memory FSM). And if we adopt Prefect, Prefect already owns run/task state, so
`transitions` would be redundant either way.

**Treat Prefect as a future *execution substrate*, not a replacement of the Arazzo
contract** (decision deferred — this ADR records the direction, not adoption):

- Keep **Arazzo canonical** and keep the executor behind the `ApplicationService` / Port
  boundary, so a Prefect integration can be added without touching the domain. Two viable
  shapes to evaluate later: (a) a Prefect flow that *drives* the existing executor; (b)
  *generating* Prefect tasks/flows from the Arazzo spec (steps → tasks, `goto`/`end` → flow
  control, `foreach` → mapping/subflows). In both, **Prefect owns state, retries,
  scheduling, resume, and observability**.
- Preserve ADR 0003 with a **channel split**: keep the synchronous executor for the in-band
  `[BLOCK_REST]` REST path; use Prefect for the **async/bulk** channel and long-running /
  resumable workflows (e.g. mass odonimo suppression). This matches the standing design note
  that the async/partial state machine belongs to the bulk channel only.

When the async/bulk need becomes real, run a spike and a dedicated ADR covering: driver vs
codegen, how coalesce/foreach map onto Prefect, the synchronous-vs-durable boundary, and
the relation to the SDK's async token refresh (anncsu-sdk#35).

## Consequences

- No premature dependency or bespoke state-management code now; the ephemeral
  `ExecutionContext` remains adequate for the synchronous path.
- The `ApplicationService`/Port boundary (ADR 0004) is what keeps Prefect adoptable later
  without rewriting the domain — a reason to keep that seam clean.
- The team has a recorded direction: do not build a hand-rolled state machine; durability
  and orchestration, if needed, come from Prefect on the async/bulk channel.
- The actual adoption remains an open, deferred decision; this ADR stays `Proposed` until a
  spike confirms the integration shape.
