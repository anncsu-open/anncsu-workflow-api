# 22. Structured per-step messages in workflow responses

Date: 2026-06-17

## Status

Accepted (refines ADR 0008; extends the output contract of ADR 0005)

## Context

Every workflow response carried a single free-text `message` ("Workflow completed")
and a vestigial `errors` field — always `null` on the 2xx path, because real
failures are RFC 7807 Problems (ADR 0008), not this model. The caller could not see
what each step did: whether `crea-accesso-per-odonimo` *created* the accesso or
*found it already existing*, or that a search step hit a handled `404`
("zero results"). The overall outcome and the per-step detail were conflated into
one opaque string.

## Decision

Replace `message` and drop `errors` in the workflow output models with:

- **`summary: str`** — the overall human outcome (formerly `message`, e.g.
  "Workflow completed"). This is success-side: RFC 7807 has no equivalent, because a
  completed run is not a Problem and must not pretend to be one.
- **`messages: list[StepMessage]`** — an ordered trace, one entry per executed step
  of the main workflow.

`StepMessage = { step, status, title, detail }`:

- `step`: the step id.
- `status`: the upstream HTTP status code of that step's call (the per-step analogue
  of the Problem `status`).
- `title` / `detail`: the upstream problem fields, **reusing RFC 7807 vocabulary** so
  a step anomaly reads like the Problem returned on a hard failure; both `null` on a
  clean 2xx step.

`success` is unchanged. `errors` is removed: it was always `null` on the success
path, and failures remain RFC 7807 Problems carrying the upstream reason and the
request id.

The engine records a **generic** per-step trace (`WorkflowRun.trace`: step id, status
code, upstream body) for each executed step. Steps skipped by `x-when` (ADR 0021) and
`foreach` sub-workflow steps are not recorded — they are not steps of the main flow.
The API layer maps the trace to `messages`, extracting `title`/`detail` from the
upstream body with the same mapper (`StepMessage.from_trace`).

**On failure the trace is preserved too.** A failing run carries the partial trace out
on the exception (`StepFailedError.trace`; `TransportError.trace` for a transport
failure, which records the in-flight step with a null `status`), and the RFC 7807
Problem (ADR 0008) exposes it as the same `messages` extension member. So a caller sees
*where* a run stopped — which steps ran and the failing one — on both the success and
the failure path.

## Consequences

- The per-step trace **subsumes the "created vs already-existing" discriminator**:
  the trace shows `verifica-accesso → 404` then `crea-accesso → 200` (created) versus
  `verifica-accesso → 200` and no create step (already existing). No dedicated field
  is needed.
- Diagnostic vocabulary is consistent across success (`messages[].status/title/detail`)
  and failure (Problem `status/title/detail`).
- The engine stays generic: it records the raw trace; the ANNCSU-specific
  `title`/`detail` extraction lives in the API layer.
- `message`→`summary` and the removal of `errors` change every workflow output model,
  its route mapping, the factories, and the tests; the new field descriptions get the
  i18n overlay (ADR 0005).
- `messages` carries only `title`/`detail` (not the full upstream `data`), so search
  responses stay compact.
