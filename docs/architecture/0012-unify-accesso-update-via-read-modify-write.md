# 12. Unify accesso updates via a read-modify-write patch

Date: 2026-06-13

## Status

Accepted

Supersedes the coordinate-only-by-progressive workflow of
[ADR 0009](0009-direct-coordinate-update-by-access-progressive.md) and the
"keep the dedicated coordinate workflow" stance of
[ADR 0010](0010-direct-accesso-operations-by-national-progressive.md) /
[ADR 0011](0011-remove-denomination-based-coordinate-update.md). Adds a new
`x-executor` capability (payload coalesce), so it also extends ADR 0003.

## Context

The facade had two ways to touch an accesso by progressive: the dedicated
coordinate workflow (`aggiorna-coordinate-da-progressivo-accesso`, via the
`gestionecoordinate` API) and the generic update
(`aggiorna-accesso-da-progressivo`, via the accessi `R` operation). The goal is
**one endpoint** for every accesso update.

The obstacle was the `R` replace semantics: a partial payload would wipe the
fields the caller omitted. Recovering the current state from the consultation
API to rebuild a complete `R` almost works — `elencoaccessiprog` exposes
`civico`, `esp`, `specif`, `metrico`, `coordX`/`coordY`, `quota`, `metodo` — but
**not `sezione_censimento`**, which is mandatory and non-nullable for `R`. So:

- `sezione_censimento` **cannot be fetched** and must be a **required input**.
- everything else **can be fetched** and used to preserve unspecified fields.

Expressing "use the caller's value if provided, else the value just read" is a
per-field coalesce inside the request payload. Arazzo 1.0 cannot express it —
the same class of gap that `x-executor.coalesce`/`foreach` already fill for
outputs and iteration.

## Decision

**One endpoint, `aggiorna-accesso-da-progressivo`, implemented as a
read-modify-write patch.** The workflow:

1. **reads** the accesso (`elencoaccessiprog` by `prognazacc`);
2. **writes** an `R` whose payload coalesces, per field, the caller input over
   the value read in step 1; `sezione_censimento` comes from input only.

`aggiorna-coordinate-da-progressivo-accesso` is **removed**: a coordinate-only
change is now this endpoint with only the coordinate fields set (the read
preserves the rest).

### New `x-executor` capability: payload coalesce

A request-body value may be a single-key object `{ "x-coalesce": [expr, expr, …] }`.
The executor resolves the expressions in order and uses the first non-null **and
non-empty** value (empty strings are skipped, like `x-join` — ADR 0020), applied
inside a payload. The empty-string skip matters here: the consultation returns `""`
for absent fields (`specif`, `metrico`, `esp`, … — confirmed on collaudo), so a
naive "first non-null" would re-send an empty `specificita`, which the upstream
rejects as invalid (must be `R`/`N`/`ROSSO`/`NERO`). Skipping `""` omits the unset
attribute instead of blanking it. Example:

```yaml
accesso:
  numero:
    x-coalesce: [$inputs.numero, $steps.leggi-accesso.outputs.numero]
  sezione_censimento: $inputs.sezione_censimento   # input only (not readable)
```

Resolution stays pure and declarative: the field mapping (consultation
`civico` → write `numero`, `esp` → `esponente`, …) lives in the spec, not in code.

### Input contract

Required: `codcom`, `prognaz`, `prognazacc`, `sezione_censimento`. Optional (omit
to preserve the current value): `numero`/`metrico`, `esponente`, `specificita`,
`isolato`, `codice_civico_comunale`, coordinates (`coordinata_x`/`_y`/`_z`,
`metodo`), `data_validita`. `numero`/`metrico` stay mutually exclusive when
provided; coordinates stay co-dependent (x with y, z/metodo with x/y). The
published OpenAPI carries **named request examples** (coordinate-only,
attribute-only, mixed).

`isolato` and `codice_civico_comunale` are not exposed by the consultation API,
so if the caller omits them they cannot be preserved and `R` may clear them
(replace). They are accepted as optional inputs; the route documents that an
accesso using them must include them. Confirming whether `R` preserves
truly-unspecified fields remains the open UAT item.

## Consequences

- A single accesso-update endpoint; coordinate-only updates need only identity +
  `sezione_censimento` + coordinates, the rest is preserved by the read.
- Every update costs one extra consultation read; acceptable for correctness and
  the minimal-input ergonomics.
- The executor gains a small, reusable payload-coalesce primitive.
- **Breaking**: `aggiorna-coordinate-da-progressivo-accesso` is gone.
- `sezione_censimento` is mandatory on every accesso update, as it is for `R`.
