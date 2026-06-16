# 20. Accesso search semantics: accparz format and prognazacc determinism

Date: 2026-06-16

## Status

Accepted (refines ADR 0018; adds a workflow alongside ADR 0016)

## Context

Exercising the accessi search and creation against PDND collaudo, plus a
confirmation from Agenzia delle Entrate, established how ANNCSU identifies and
matches an accesso. These findings drive the search/create design.

### How ANNCSU matches an accesso

- **`accparz` is the only detail-returning filter.** `elencoaccessiprog` (by
  odonimo `prognaz`) and `elenco_accessi` (by `denom`) both take only `accparz`;
  `esisteAccesso` returns a boolean (no details); **no operation looks up an
  accesso by exact civico/esponente/specificità**.
- **`accparz` is a partial (contains) match**, not an exact lookup: `accparz="15"`
  also matches `115`, `1501`, `2150`, … (validated on VIA AURELIA).
- **`accparz` value format (confirmed by Agenzia delle Entrate):** `civico`, then
  `/esponente` if an esponente is present, then `-specificità` if a specificità is
  present — e.g. `95`, `95/A`, `95/A-ROSSO`. The esponente separator is **always
  `/`**; the specificità is appended to the esponente with **`-`**.
- **The concatenated form does not match.** Validated on VIA AURELIA, VIA TARANTO,
  VIA APPIA NUOVA: `95/A` matches civico 95 / esp A, while `95A` and `95 A` return
  nothing. The slash is required.
- **Storage vs query.** The data stores `civico`, `esp`, `specif` as **separate
  fields** (and every accesso carries a `prognazacc`); the `/`…`-` form is only the
  *query* shape for `accparz`.

### Determinism

- civico (+esponente +specificità) via `accparz` can **never be guaranteed unique**:
  the contains-match can over-match a longer civic (e.g. `95/A` would also match a
  hypothetical `195/A`).
- **The deterministic identity of an accesso is its `prognazacc`** (national
  progressive), returned with every search result.

## Decision

1. **Build `accparz` with `x-join` using the AdE separators.** `x-join` joins parts
   with a separator and drops absent parts (and their separators). Nesting yields
   the AdE format:
   `x-join("-", x-join("/", civico, esponente), specificità)` → `95` / `95/A` /
   `95/A-ROSSO`.

2. **Search disambiguates; it does not pinpoint.** The read-only search returns the
   candidate accessi (`civico`/`esp`/`specif`/`prognazacc`); the caller selects the
   exact one. The search is keyed by the odonimo (`prognaz`, or denomination with
   the ADR 0018 disambiguation). It **keeps** the optional `esponente` (and
   `specificità`) as a narrowing filter, now built with the correct AdE format via
   `x-join` (the previous concatenated form was a bug).

3. **Deterministic actions key off `prognazacc`.** `aggiorna-accesso-da-progressivo`
   and `sopprimi-accesso` already take `prognazacc`. Any operation acting on a
   specific accesso uses the `prognazacc` obtained from the search — never an
   `accparz` match.

4. **A new workflow adds an accesso to an existing odonimo, scoped to its
   `prognaz`.** `crea-accesso-per-odonimo` takes a **mandatory `prognaz`** and
   verifies existence via `elencoaccessiprog(prognaz, accparz)` with the AdE format
   (instead of the civic-only `esisteAccesso`): no match → create; exactly one →
   return its `prognazacc`; more than one → fail (ambiguous, like ADR 0019). It
   creates the accesso on that odonimo directly. `verifica-e-crea-indirizzo-completo`
   is **unchanged** — it still resolves/creates the odonimo by denomination
   (ADR 0016/0019); the new workflow is the deterministic, odonimo-already-known
   path (symmetric with the search split of ADR 0018).

## Consequences

- `accparz` construction is deterministic and correct (AdE separators); matching
  remains a partial filter, so the search is for discovery, not identity.
- Determinism where it matters (writes) is preserved via `prognazacc`.
- `crea-accesso-per-odonimo` is fully deterministic on the odonimo (`prognaz`) and
  refuses ambiguous accessi rather than guessing; the existing denomination-based
  create is left intact for the create-the-odonimo case.
