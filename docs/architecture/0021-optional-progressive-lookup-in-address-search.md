# 21. Optional progressive lookup in address search via a conditional step entry

Date: 2026-06-16

## Status

Accepted (extends ADR 0018; adds the `x-when` executor primitive to ADR 0003)

## Context

`ricerca-indirizzo-completo` finds the odonimo by denomination
(`elencoodonimiprog` on `denomparz`) and then its accessi. A caller that already
knows the odonimo's national progressive — e.g. after the ADR 0018 disambiguation,
or from a previous result — had no way to search the address directly by that
progressive and was forced to re-search by name.

Resolving by progressive uses a **different** consultation operation,
`prognazarea` (resolves an odonimo by its `prognaz`), than resolving by name
(`elencoodonimiprog`). So the workflow must run one of two different *first*
operations depending on which input is present.

The executor runs steps sequentially from position 0 and **every step dispatches** —
there was no way to enter a workflow conditionally or skip a step without making its
upstream call. The established idiom (a `goto` over a middle step) cannot help the
*first* step; routing purely on input would otherwise force one wasted upstream call
in one of the two modes.

There is no read operation that looks up an accesso by its `prognazacc` (ADR 0020:
`prognazacc` is the write/identity key, never a query key), so the same "optional
progressive" cannot be added to `ricerca-accessi-per-odonimo` — that workflow already
keys on the odonimo `prognaz` and is left unchanged.

## Decision

1. **Add a generic `x-when` step guard to the executor.** A step may carry
   `x-when: <condition>`; when the condition is false the step is **skipped without
   dispatching** (no request, no outputs) and execution falls through to the next
   step. It is evaluated before the step's `foreach` and dispatch, using the same
   condition language as `successCriteria`. This is the conditional-entry primitive
   the engine lacked; it is workflow-agnostic and reusable (cf. `x-coalesce`,
   `x-join`, `foreach`).

2. **Extend `ricerca-indirizzo-completo` with `progressivo_nazionale` XOR
   `denom_odonimo`.** Exactly one must be provided (enforced in the input model). The
   workflow becomes:
   - `risolvi-per-prognaz` — `x-when: $inputs.progressivo_nazionale != null`;
     `prognazarea(prognaz)`. Skipped in denomination mode. On success: end if no
     `numero_civico`, else `goto cerca-accessi`. On `404`: end with empty lists
     (unknown progressive — "zero results", ADR 0014).
   - `cerca-odonimi` — the existing denomination search (`elencoodonimiprog`),
     reached by fall-through when `risolvi-per-prognaz` is skipped; keeps the
     ADR 0018 disambiguation (more than one match → return candidates, empty accessi).
   - `cerca-accessi` — unchanged, but its `prognaz` is
     `x-coalesce($inputs.progressivo_nazionale, $steps.cerca-odonimi.outputs.progressivo_nazionale)`
     so it uses whichever resolver ran. `odonimi` is coalesced across the two
     resolvers via `x-executor.coalesce`.

3. **`ricerca-accessi-per-odonimo` is unchanged** (no accesso-by-`prognazacc` read
   operation exists; see Context and ADR 0020).

## Consequences

- Address search supports both entry modes with **no wasted upstream call**: the
  unused resolver is skipped, not dispatched.
- `x-when` is a small, generic engine capability for any future workflow with
  alternative-input branches; it fills the documented "no conditional entry" gap.
- In progressive mode the returned odonimo carries `prognazarea`'s shape (it exposes
  `denomuff`, not the `duf` of `elencoodonimiprog`) — the same shape
  `ricerca-accessi-per-odonimo` already returns; `OdonimoResult` keeps both optional.
- `denom_odonimo` becomes optional at the API; the input model enforces
  exactly-one-of so the contract stays unambiguous.
