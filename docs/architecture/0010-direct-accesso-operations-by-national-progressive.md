# 10. Direct accesso update by national progressive

Date: 2026-06-12

## Status

Proposed

The decision between the two designs below is **pending an empirical
verification on the UAT environment** (see "The decisive experiment"). If
design A is confirmed, this ADR supersedes
[ADR 0009](0009-direct-coordinate-update-by-access-progressive.md); under
design B, ADR 0009 stands unchanged.

## Context

The facade has **no workflow to update an accesso's attributes** (ANNCSU
`operazione_civico = R`): it covers I (inside the upsert saga), S (suppression),
coordinate updates (a separate ANNCSU API), and reads. The same reasoning that
introduced the by-progressive coordinate variant (ADR 0009 — determinism, fewer
PDND calls, the read → write-by-id client chain) applies to attribute updates.

### Updatable fields (from the ANNCSU accessi OpenAPI)

Identification: `codcom`, the odonimo's `progr_nazionale`, and the accesso's
`progr_civico` (returned as `prognazacc` by the consultation APIs).

| Field | Max length | OAS notes |
|---|---|---|
| `numero` | 5 | civic number; not together with `metrico` |
| `metrico` | 6 | metric identification; not together with `numero` |
| `sezione_censimento` | 13 | non-nullable for I/R in the OAS |
| `esponente` | 15 | optional, I/R only |
| `specificita` | 5 | optional, I/R only |
| `isolato` | 4 | optional, I/R only |
| `codice_civico_comunale` | 30 | optional |
| `data_valid_amm` | — | optional; server defaults to the current date |
| `coordinate` (x, y, z, metodo) | 12/12/7/1 | embedded, same shape as the coordinate API |

### The open question that decides the design

Two designs are on the table:

- **Design A — one generic update, coordinates folded in.** A single
  `aggiorna-accesso-da-progressivo` workflow exposes every updatable field,
  including the embedded `coordinate`; a coordinates-only change sends the
  minimal payload (identifiers + coordinates). The coordinate-only workflows
  become redundant and are removed.
- **Design B — attributes and coordinates stay separate.** The generic update
  excludes the embedded `coordinate`; coordinate changes keep using the
  dedicated coordinate API (ADR 0009), which needs no `sezione_censimento`, no
  `numero`/`metrico`, and has no replace semantics.

Which design is sound depends on **how the server actually treats `R`**:

1. **Replace vs patch.** If `R` replaces the accesso's state, a minimal
   coordinates-only payload would silently clear `numero`, `esponente`, etc. —
   data loss disguised as a coordinate update. If omitted fields are preserved
   (patch-like), design A is safe and simpler.
2. **Minimal payload acceptance.** The anncsu-sdk CLI enforces
   `sezione_censimento` (required for I/R) and the `numero`/`metrico` mutex
   locally, but that interpretation was empirically grounded on **insert**, not
   on `R`; whether the server accepts an `R` carrying only identifiers and
   coordinates has never been observed.

Neither point can be settled from the OAS text alone.

## Decision

Deferred to the outcome of the following experiment; this ADR records the two
designs and the decision criterion.

### The decisive experiment (UAT, anncsu-sdk CLI)

Same pattern as the suppression-cascade dry-run that settled reject-vs-cascade:

1. **I** — insert a fake accesso with full attributes (`numero`, `esponente`,
   valid `sezione_censimento`).
2. **R** — send a coordinates-only minimal payload (identifiers + `coordinate`).
3. **Read back** via the consultation API (`prognazacc` exposes `civico`,
   `esp`, `specif`, `coordX/Y`): did the omitted attributes survive? Was the
   minimal `R` accepted at all (or rejected for the missing
   `sezione_censimento` / `numero`/`metrico`)?
4. **S** — clean up the fake accesso.

Outcome mapping:

- Minimal `R` accepted **and** omitted attributes preserved → **design A**:
  one generic update with embedded coordinates; remove (or deprecate) the
  coordinate-only workflows; this ADR supersedes ADR 0009.
- Minimal `R` rejected, **or** omitted attributes cleared → **design B**: the
  generic update excludes coordinates; the dedicated coordinate workflows stay
  exactly as decided in ADR 0009.

Contract rules already settled regardless of the outcome, consistent with the
sezione_censimento decision (fail early and clearly at the boundary): whatever
the server requires for `R` is validated in the facade input model with
named-field 422 problems before any PDND call; replace semantics, if confirmed,
are stated explicitly in the route documentation.

## Consequences

- The implementation of `aggiorna-accesso-da-progressivo` waits for the UAT
  verification; the experiment protocol and its result are recorded alongside
  this ADR once run.
- Under design A the published contract shrinks (one update workflow); under
  design B it grows by one route while keeping coordinates on their dedicated,
  lighter API.
- Updating the odonimo (`R` on the odonimi API) remains uncovered by the
  facade; if needed it is a separate decision following this same pattern.
