# 16. Full accesso and odonimo fields in the complete-address creation

Date: 2026-06-15

## Status

Accepted

## Context

The `verifica-e-crea-indirizzo-completo` workflow creates an odonimo (if missing)
and then an accesso. It exposes only a **minimal subset** of the fields the ANNCSU
schema accepts for creation, while the by-progressive **update** workflows
(`aggiorna-accesso-da-progressivo`, ADR 0012; `aggiorna-odonimo-da-progressivo`,
ADR 0013) already expose the full set.

- **Accesso** — the `crea-accesso` step sends only `numero`, `sezione_censimento`,
  `data_valid_amm` (with `operazione_civico: I`). The SDK's accesso object also
  accepts `metrico`, `esponente`, `specificita`, `isolato`,
  `codice_civico_comunale`, and the `coordinate` block (`x`/`y`/`z` + `metodo`) —
  none of which the creation exposes.
- **Odonimo** — the `crea-odonimo` step sends only `dug`, a `denom_delibera`
  hardcoded to the odonimo denomination, and `provvedimento.flag_delibera: "2"`.
  It omits `denom_localita`, `denom_in_lingua_1`/`_2`, `codice_comunale`, a real
  `denom_delibera`, and the full `provvedimento`/`aut_prefettura`.

A complication blocks a symmetric civic/metric creation: the existence probe
`esisteAccessoPost` accepts only `req`/`codcom`/`denom`/`accesso` (the civic
number) — it has **no metric field**, so a metric accesso cannot be pre-verified
through it.

## Decision

Bring the creation workflow to **field parity** with the update workflows, and
support metric-based accesso creation.

### 1. One create step, all fields (no duplicated pipelines)

`CreaIndirizzoCompletoInput` and the `crea-accesso` / `crea-odonimo` steps expose
the full creation field set. A single create step per entity maps every field; the
executor's null-pruning (`_without_unset`, ADR 0003) drops the unset ones, so there
is **no need to duplicate steps** per field combination. Validation is reused from
the update models: the `numero`/`metrico` mutual exclusion, the WGS84 coordinate
bounds and their co-dependence, the `flag_delibera` rules, and the date checks.

- Accesso adds: `metrico`, `esponente`, `specificita`, `isolato`,
  `codice_civico_comunale`, and `coordinata_x`/`_y`/`_z` + `metodo`.
- Odonimo adds: `denom_localita`, `denom_in_lingua_1`/`_2`, `codice_comunale`, a
  real `denom_delibera`, `provvedimento`, and `aut_prefettura`.

New fields are **optional** (backward compatible: existing minimal calls keep
working). The currently required fields stay required; an accesso must carry
**exactly one** of `numero`/`metrico` (at least one, mutually exclusive).

### 2. Metric accesso: skip the civic existence check

Because `esisteAccessoPost` is civic-only, the workflow forks before the existence
probe:

- **civic input** (`numero`): `verifica-accesso` → if it exists go to
  `cerca-accesso`, otherwise `crea-accesso` (today's behaviour);
- **metric input** (`metrico`): route straight to `crea-accesso`. There is no
  metric existence probe, so the create runs directly; a duplicate surfaces as the
  API's `esito != 0` and is mapped to a Problem (ADR 0008).

This is a single conditional route plus the shared create step — not a duplicated
verify/create pipeline. (A dedicated metric existence probe via another
consultation API is possible but out of scope here.)

### 3. Odonimo creation no longer hardcodes the delibera

The hardcoded `denom_delibera = denom_odonimo` and `flag_delibera = "2"` are
replaced by real inputs, keeping a sensible default so existing minimal calls still
succeed.

## Consequences

- Creation reaches field parity with the update workflows; an address can be
  created with its full accesso attributes, coordinates, and odonimo metadata, and
  metric-based accessi are supported.
- Backward compatible: the new fields are optional and the previously required
  fields are unchanged; existing minimal payloads keep working.
- The metric branch trades the "already exists → return the progressivo" path for a
  direct create (duplicate → `esito != 0`), because the consultation layer cannot
  verify a metric accesso. This limitation is documented, not worked around.
- The input model, the Arazzo spec, the localized OpenAPI examples, the i18n
  catalog, and the tests (route, model validation, regression) all grow to cover
  the added fields and the civic/metric fork.
- Validators and the `numero`/`metrico` rule are shared with the update models
  (ADR 0012/0013), so the rules stay defined once.
