# 9. Direct coordinate update by access progressive

Date: 2026-06-12

## Status

Accepted

(Extends the canonical Arazzo contract of ADR 0002 with a new workflow; no change
to the engine of ADR 0003 or to the hexagonal layering of ADR 0004.)

## Context

The only way to update the coordinates of an accesso today is the
`aggiorna-coordinate-accesso` workflow, which identifies the accesso by
denomination: it searches the odonimo (`elencoodonimiprog` with `denomparz`),
then the accesso (`elencoaccessiprog` with `accparz`), and only then calls
`gestionecoordinate`. Three observations make a direct variant necessary:

1. **The write operation does not need the denomination.** `gestionecoordinate`
   takes only `codcom`, the accesso's national progressive (`progr_civico` in the
   write payload, the same value the consultation API returns as `prognazacc`),
   and the coordinates. The two search steps exist purely to resolve
   denomination → `prognazacc`.
2. **Clients already hold the progressive.** `ricerca-indirizzo-completo` returns
   `prognazacc` for every accesso it finds, and
   `verifica-e-crea-indirizzo-completo` returns the created `progressivo_civico`.
   The natural client flow — search or create, then update coordinates by
   identifier — is impossible without re-resolving by denomination.
3. **Denomination-based resolution is non-deterministic for a write.** The
   searches are partial matches and the workflow takes `data[0]`: with an
   ambiguous denomination (e.g. "ROMA" matching both VIA ROMA and PIAZZA ROMA)
   the coordinates of the *first* match are silently updated. Identifying the
   target by progressive removes the ambiguity. It also reduces the PDND calls
   per update from three to one, which matters under PDND rate limiting.

Arazzo 1.0 cannot express "skip the leading search steps when the progressive is
already provided": `criteria` are evaluated only *after* a step has run, so there
is no pre-step guard that could branch on `$inputs`.

## Decision

Add a dedicated single-step workflow to the canonical Arazzo spec:

- **`aggiorna-coordinate-da-progressivo-accesso`** — inputs `codcom`,
  `prognazacc` (the accesso's national progressive, named as the consultation
  API returns it), and the coordinate fields; one step calling
  `anncsu-coordinate.gestionecoordinate`; same `successCriteria`
  (`$statusCode == 200`, `esito == "0"`) and output shape as the final step of
  the existing workflow.

The facade exposes it as its own typed route,
`POST /v1/workflows/aggiorna-coordinate-da-progressivo-accesso`, following the
one-route-per-workflow pattern. The by-denomination workflow remains available
for callers that start from a denomination.

No engine or executor change is involved: the domain flow lives in the spec
(ADR 0004) and the generic engine already runs linear single-step workflows.

## Consequences

Easier:
- Deterministic coordinate updates: the caller names the exact accesso.
- One PDND call instead of three for the identifier-based flow.
- The natural client chain (search/create → update by `prognazacc`) is now
  expressible against the API.

More difficult / accepted costs:
- The spec and the published contract grow by one workflow and one route; the
  generated workflows documentation page must be regenerated.
- Two workflows now share the coordinate-update semantics; a change to the
  `gestionecoordinate` step must be applied to both.
- The `data[0]` partial-match fragility of denomination-based *writes* remains
  in `aggiorna-coordinate-accesso` (and its siblings). Tightening those
  workflows (e.g. requiring a unique match) is a separate decision, not taken
  here.
