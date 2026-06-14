# 13. Odonimo update by national progressive (read-modify-write)

Date: 2026-06-14

## Status

Accepted

Applies the read-modify-write patch pattern of
[ADR 0012](0012-unify-accesso-update-via-read-modify-write.md) to the odonimo
aggregate. Reuses the `x-coalesce` payload primitive (no engine change). Extends
the canonical Arazzo contract of ADR 0002.

## Context

The facade can create an odonimo (inside `verifica-e-crea-indirizzo-completo`) and
suppress one (`sopprimi-odonimo-completo`, which must cascade the accessi first),
but it cannot **update** an odonimo's attributes (ANNCSU operation `R`). This is
the exact gap ADR 0012 closed for accessi, applied to odonimi.

The same obstacle applies: `R` replaces the odonimo's state, so a partial payload
risks wiping unspecified fields. The consultation API (`prognazareaPost`, lookup by
the odonimo's national progressive) exposes only part of the state:

- **Fetchable** (preserved by the read): `dug`, `denom_localita`, `denom_in_lingua_1`,
  `denom_in_lingua_2`, `codice_comunale` (from `dug`/`denomloc`/`denomlingua1`/
  `denomlingua2`/`cododocomunale`).
- **Not fetchable** (administrative-act fields): `denom_delibera`, `provvedimento`
  (delibera flag + data/protocollo), `aut_prefettura` (prefecture authorization).

## Decision

Add `aggiorna-odonimo-da-progressivo` — a single endpoint, read-modify-write patch:

1. **leggi-odonimo** — `anncsu-consultazione.prognazareaPost` (unique 0/1 hit by the
   odonimo progressive) → outputs the fetchable fields.
2. **aggiorna-odonimo** — `anncsu-odonimi.gestioneAnncsuOdonimiPdnd` with
   `tipo_operazione: R`, payload merging caller input over the read via `x-coalesce`
   for each fetchable field. `denom_delibera`/`provvedimento`/`aut_prefettura` come
   from input only (not fetchable).

### Input contract

Required: `codcom`, `prognaz`, and **`denom_delibera`**. `denom_delibera` is the
odonimo's core denomination and is not fetchable, so under replace semantics it is
required to avoid silently dropping it — the faithful analogue of
`sezione_censimento` for accessi. (The SDK does not strictly force it for `R`; this
is our conservative, replace-safe choice.)

Optional (preserved from the read when omitted): `dug`, `denom_localita`,
`denom_in_lingua_1`, `denom_in_lingua_2`, `codice_comunale`, `data_validita`.

Optional administrative objects, validated up front (fail early with a named field,
not an opaque server error) — mirroring how the accesso model validates its own
co-dependencies, but with the odonimi rules from the SDK `odonimo_validation.py`:

- `provvedimento.flag_delibera` ∈ `0..4`; values `0`/`1` require
  `provvedimento.data` and `provvedimento.protocollo`.
- `aut_prefettura`: `data_pref` and `protocollo_pref` are co-required (both or
  neither).
- `data_valid_amm` is a valid `DD/MM/YYYY` date, not in the future.

There is **no** mutex between `provvedimento` and `aut_prefettura` (they are
independent administrative references); the co-dependencies are internal to each.

## Consequences

- Odonimo attribute updates are now reachable, deterministic (by progressive), and
  replace-safe; fields the caller omits are preserved by the read.
- Each update costs one extra consultation read (acceptable, as for accessi).
- No engine change: `x-coalesce` is reused.
- `denom_delibera` is mandatory on every odonimo update.
- Open (UAT, mirrors ADR 0012): whether `R` truly replaces vs patches unspecified
  fields, and the exact required companions for a given `flag_delibera` — handled
  conservatively here.
