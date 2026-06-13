# 10. Direct accesso update by national progressive

Date: 2026-06-12

## Status

Accepted

Design B below is adopted **now** as the initial, hypothesis-safe contract; the
UAT experiment becomes an *evolution gate* that can only relax it (see
Decision). [ADR 0009](0009-direct-coordinate-update-by-access-progressive.md)
stands unchanged.

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

The generic update carries the **full accesso state, coordinates included** —
this is settled (see Decision): a full-state replace including `coordinate` is
safe under both server behaviours, and *omitting* coordinates would let an
attribute update wipe them. The remaining open question is only whether a
**coordinates-only change** may use a minimal `R`:

- **Design A — fold coordinate-only changes into a minimal `R`.** A
  coordinates-only update sends `R` with identifiers + coordinates only; the
  dedicated coordinate workflows become redundant and are removed.
- **Design B — keep the dedicated coordinate API for coordinate-only changes**
  (ADR 0009): it needs no `sezione_censimento`, no `numero`/`metrico`, has no
  replace semantics, and is the lighter path for bulk coordinate campaigns.

Which is sound depends on **how the server actually treats `R`**:

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

**Implement design B now, as the hypothesis-safe contract.** Waiting for the
experiment would block the missing capability; implementing design A without it
would risk silent data loss. Design B is correct under *both* server
behaviours:

- `aggiorna-accesso-da-progressivo` requires the **full desired state**:
  `codcom`, `prognaz`, `prognazacc`, `sezione_censimento`, exactly one of
  `numero`/`metrico` (validated in the facade model with a named-field 422),
  plus the optional attributes (`esponente`, `specificita`, `isolato`,
  `codice_civico_comunale`, `data_validita`).
- The route documents **replace semantics**: the request describes the
  accesso's new state; attributes left out are not guaranteed preserved.
  Callers updating a single attribute read the accesso first
  (`ricerca-indirizzo-completo`) and send the full state back.
- **Coordinates are part of that state and are exposed here** (embedded
  `coordinate` of the accessi API: `coordinata_x`/`_y`/`_z`/`metodo`, optional
  but co-dependent — x and y together, z and metodo only with x and y, same
  WGS84 rules as the coordinate workflows). This is *required* by the replace
  stance: if the generic update could not carry coordinates, updating an
  attribute would wipe the accesso's coordinates whenever `R` is a replace.
  It does **not** reopen design A — this is the full-state path, not a minimal
  coordinates-only payload; the dedicated coordinate workflows (ADR 0009) stay
  as the lighter, targeted path for coordinate-only changes.
- Input fields the caller leaves unset are **omitted from the wire**, not sent
  as nulls (the embedded `coordinate` block disappears entirely when no
  coordinate is given): under replace semantics an explicit `null` and an absent
  field may mean different things server-side, and the facade has no way to
  express "clear this field" intentionally.

If `R` is a replace, the contract is honest. If `R` turns out to be patch-like,
the contract is merely stricter than necessary — and loosening it later is
non-breaking, while tightening it would not be.

### The UAT experiment, now an evolution gate

The experiment (protocol: I with full attributes → minimal coordinates-only
`R` → read back via consultation → S cleanup, same pattern as the
suppression-cascade dry-run) no longer blocks anything. Its outcome decides a
possible *relaxation*:

- `R` patch-like and minimal payloads accepted → optional fields may become
  truly optional (omitted = preserved), and the dedicated coordinate-only
  workflows could be folded into a minimal `R` (design A) and deprecated.
- `R` is a replace or minimal payloads rejected → the contract is already
  exactly right; nothing changes.

## Consequences

- The capability ships now; the published contract can only be relaxed by the
  experiment's outcome, never broken.
- Until the experiment runs, single-attribute updates require a read-first,
  send-full-state round trip — inconvenient but safe, and stated in the route
  documentation.
- Under a later move to design A the contract would shrink (one update
  workflow); the coordinate workflows would be deprecated, not silently
  removed.
- Updating the odonimo (`R` on the odonimi API) remains uncovered by the
  facade; if needed it is a separate decision following this same pattern.
