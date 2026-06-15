# 18. Align address search with the SDK: disambiguate odonimi, target by prognaz

Date: 2026-06-15

## Status

Accepted

## Context

The read-only search workflow `ricerca-indirizzo-completo` resolves an odonimo by
denomination (`elencoodonimiprog`, `denomparz`) and then lists its accessi
(`elencoaccessiprog`). It always uses the **first** match,
`$response.body.data[0].prognaz`, and exposes only `numero_civico` as the access
filter.

The anncsu-sdk CLI (`anncsu pa accessi`, `cli/commands/pa.py`) does the same
two-step resolve-then-list, but differently in two ways that matter:

- **It never silently picks the first match.** `--denom` is a substring search; when
  it matches more than one odonimo the command stops and lists the candidates with
  their `prognaz`, telling the caller to re-run with `--prognaz`. `--denom` and
  `--prognaz` are mutually exclusive.
- **`accparz` is civic *or* metric.** The parameter is documented as "valore anche
  parziale del civico (+eventuale esponente e/o specificità) **oppure metrico**".
  There is no separate metric search field; `metrico` is an output column only.

Our single-`data[0]` behaviour has two consequences. A denomination such as
"AURELIA" matches 11 odonimi (CIRCONVALLAZIONE, RAMPA, VIA AURELIA, …); the search
silently queries the accessi of whichever comes first (CIRCONVALLAZIONE) and there
is no way to reach a specific one (e.g. VIA AURELIA, prognaz 907720). And because
the only entry point is the denomination, a caller that already knows the odonimo
progressive cannot target it, nor list its metric accessi.

The executor runs step 0 unconditionally and has no conditional-entry / step-skip
primitive, so a single workflow cannot cleanly switch its first operation between
"resolve by denomination" and "resolve by progressive".

## Decision

### 1. Disambiguate in `ricerca-indirizzo-completo`

When `cerca-odonimi` returns more than one match, end the workflow with the full
list of odonimi and an empty `accessi` list, instead of querying `data[0]`. This
mirrors the SDK's "never silently pick the first match": the caller gets every
candidate with its `prognaz` and can re-query the one it wants.

The condition is expressible today (`$response.body.data.length > 1`; the spec
already uses `.length` comparisons). The accessi step is reached only when exactly
one odonimo matches and a civic was supplied. Evaluation order of the
`onSuccess` actions:

1. end if `numero_civico` is absent (existing skip);
2. end if `data.length > 1` (new — ambiguous, return candidates);
3. fall through to `cerca-accessi` (one match, civic supplied).

### 2. New workflow `ricerca-accessi-per-odonimo`

Add a second search workflow that takes a `prognaz` directly, mirroring
`anncsu pa accessi --prognaz`:

- `leggi-odonimo` — `prognazarea(prognaz)` resolves the odonimo; its data shape
  (`prognaz`, `dug`, `duf`, `cododocomunale`, `denomloc`, `denomlingua1/2`) matches
  `OdonimoResult`. A 404 ends with empty results (the search convention from the
  existing 404-as-empty handling).
- `cerca-accessi` — `elencoaccessiprog(prognaz, accparz)` lists the accessi; a 404
  ends with an empty `accessi` list.

Inputs: `prognaz` and `numero_civico` (mapped to `accparz`), both required — see
decision 3. Output reuses `RicercaIndirizzoOutput` (the resolved odonimo as a
single-element `odonimi` list plus `accessi`). This is the path that reaches a
specific odonimo and — because `accparz` carries either a civic or a metric value —
lets a caller list metric accessi.

### 3. `accparz` is required — `numero_civico` is mandatory in the new workflow

ANNCSU's `elencoaccessiprog` **requires** `accparz`: a `prognaz`-only call fails
(a non-404 error, surfaced as a 422), it does not return "all accessi". The SDK CLI
works around this by defaulting `accparz` to `"1"`.

We do **not** copy that default. In `ricerca-accessi-per-odonimo`, `numero_civico`
(which maps to `accparz`) is a **required** input. A magic `"1"` default would be
dishonest: `accparz` is a partial match, so `"1"` returns only the accessi whose
civic/metric contains `"1"` (for VIA AURELIA, 279 of them) — a filtered subset, not
the complete list. The ANNCSU API offers no unfiltered listing, so rather than
imply one we require the caller to supply the civic-or-metric filter explicitly.

### 4. Keep `numero_civico` as the public field name

`numero_civico` maps to `accparz`, which accepts a civic *or* a metric value. The
field is **not** renamed; the dual meaning is documented on the field and in the
workflow docs. Renaming the public input is rejected to keep the API stable.

## Alternatives considered

- **One workflow with a conditional first step (denom XOR prognaz).** Rejected: the
  executor has no step-skip primitive, so this would require either a new executor
  feature or a fragile fallback that calls `prognazarea` with a null `prognaz` and
  relies on the API erroring to branch to the denomination search. Two workflows
  map the SDK's two mutually-exclusive resolution modes without engine changes.
- **Renaming `numero_civico` to `accparz`.** Rejected per decision 3 (API stability);
  documented instead.

## Consequences

- A caller can target a specific odonimo by `prognaz` and list its accessi,
  including metric accessi (via `accparz`).
- An ambiguous denomination returns all candidates (HTTP 200) instead of silently
  searching the wrong odonimo; the caller re-queries with the chosen `prognaz`.
- No executor changes; both behaviours use existing primitives
  (`onSuccess`/`onFailure`, `goto`/`end`, `.length`, `$inputs.X != null`).
- Search is split across two endpoints (`ricerca-indirizzo-completo` by
  denomination, `ricerca-accessi-per-odonimo` by progressive), matching the SDK's
  `--denom` / `--prognaz` split.
- `numero_civico` keeps a dual civic/metric meaning; this is documentation-only and
  could confuse a reader who takes the name literally.
