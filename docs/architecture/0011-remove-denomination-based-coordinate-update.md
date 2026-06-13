# 11. Remove the denomination-based coordinate update workflow

Date: 2026-06-13

## Status

Accepted

(Resolves the fragility ADR 0009 explicitly deferred; follows from the
by-progressive determinism of ADR 0009 and ADR 0010. Breaking change to the
published `/v1` contract.)

## Context

Three workflows could update an accesso's coordinates:

- `aggiorna-coordinate-accesso` — identifies the accesso **by denomination**
  (`elencoodonimiprog` with `denomparz`, then `elencoaccessiprog` with
  `accparz`), taking `data[0]` of each partial-match search, then writes via the
  dedicated coordinate API.
- `aggiorna-coordinate-da-progressivo-accesso` (ADR 0009) — by `prognazacc`,
  dedicated coordinate API, deterministic, lightweight.
- `aggiorna-accesso-da-progressivo` (ADR 0010) — full-state accesso replace via
  the accessi API, coordinates included.

ADR 0009 kept the denomination-based workflow but flagged its `data[0]`
partial-match write as a fragility to address in "a separate decision". With two
deterministic, by-progressive paths now available, that workflow is the only
**non-deterministic write** left in the facade: an ambiguous denomination
(e.g. "ROMA" matching VIA ROMA and PIAZZA ROMA) silently writes coordinates onto
the first match. For a write, that is a latent data-integrity bug, and the
workflow no longer fills a gap — a caller starting from a denomination runs
`ricerca-indirizzo-completo` to get `prognazacc`, then uses a by-progressive
workflow.

## Decision

**Remove `aggiorna-coordinate-accesso`** from the canonical Arazzo spec and the
published `/v1` contract, together with its dedicated input model
(`AggiornaCoordinateInput`) and route. The `AggiornaCoordinateOutput` shape stays
(shared with the by-progressive coordinate workflow).

Coordinate updates are therefore always addressed by national progressive:
`aggiorna-coordinate-da-progressivo-accesso` for coordinate-only changes (the
lighter path) and `aggiorna-accesso-da-progressivo` when updating coordinates as
part of the accesso's full state.

## Consequences

- No non-deterministic write remains in the facade; coordinate updates always
  target an explicit accesso.
- **Breaking**: clients calling `POST /v1/workflows/aggiorna-coordinate-accesso`
  must switch to resolving `prognazacc` first (via `ricerca-indirizzo-completo`)
  and calling a by-progressive workflow.
- The same `data[0]` partial-match pattern still exists in the *read* steps of
  the upsert saga (`verifica-e-crea-indirizzo-completo`) and in
  `ricerca-indirizzo-completo`; those are reads, lower risk, and out of scope
  here.
