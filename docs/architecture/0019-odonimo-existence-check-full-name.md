# 19. Build the odonimo existence-check name with x-concat

Date: 2026-06-16

## Status

Accepted

## Context

`verifica-e-crea-indirizzo-completo` decides whether to create an odonimo or reuse
an existing one. Its first step, `verifica-odonimo`, calls `esisteOdonimo` with
`denom: $inputs.denom_odonimo` (the bare denomination, e.g. `"AURELIA"`).

Exercising the write path against collaudo revealed this is wrong. ANNCSU's
`esisteOdonimo` `denom` parameter requires the **full street name**,
`DUG + " " + DENOMUFF` (e.g. `"VIA AURELIA"`); given only the denomination it
returns `data=false` even for streets that exist (confirmed in the anncsu-sdk
notes — the SDK builds the full name before calling `esiste_odonimo`). So our
step always sees `false`, always falls through to `crea-odonimo`, and for an
existing odonimo the creation fails (`step 'crea-odonimo' failed`). The write
auth is fine — the SDK writes successfully against the same environment.

There is a second, coupled problem. If we simply fixed `esisteOdonimo` to return
`true`, the flow would proceed to `cerca-odonimo`, which resolves the odonimo's
progressive from `elencoodonimiprog(denomparz=...)` and takes `data[0].prognaz`.
A denomination shared across several `dug` (CIRCONVALLAZIONE / RAMPA / VIA
"AURELIA") matches many odonimi, and `denomparz` cannot be narrowed by `dug`
(the operation has no such parameter, and the expression language cannot filter a
list). Taking `data[0]` would silently create the accesso on the **wrong** odonimo.
Fixing the existence check alone would trade a visible failure for a silent
mis-write.

The expression language has no string concatenation, so the full name cannot be
built from `dug` and `denom_odonimo` inside the payload today.

## Decision

### 1. `x-concat` payload primitive

Add an `x-concat` primitive to the engine, a sibling of `x-coalesce`:
`{"x-concat": [op1, op2, ...]}` resolves each operand (expression or literal) and
joins them as strings, treating `null` as an empty string. It is resolved in
`resolve_value`, so it works anywhere in a request payload.

### 2. Pass the full name to `esisteOdonimo`

`verifica-odonimo` builds the name ANNCSU expects:

```yaml
denom:
  x-concat:
    - $inputs.dug
    - " "
    - $inputs.denom_odonimo
```

`cerca-odonimo` keeps `denomparz: $inputs.denom_odonimo` (a partial match, the
format that operation wants).

### 3. Refuse an ambiguous odonimo instead of mis-writing

`cerca-odonimo` requires exactly one match (`$response.body.data.length == 1` in
`successCriteria`). When a denomination is shared across several `dug`, the step
fails with a clear error (surfaced as a 422 with the upstream body, ADR 0014)
rather than silently creating the accesso on `data[0]`. Creating on a
shared-denomination odonimo is therefore not supported through this denomination
input alone; a caller hitting it must use a denomination that is unique within the
municipality (a future `prognaz` input could target a specific odonimo directly,
mirroring the SDK's `--prognaz` — out of scope here).

## Alternatives considered

- **Caller passes the full name in `denom_odonimo`.** Rejected: `cerca-odonimo`'s
  `denomparz` matches the denomination only (`"AURELIA"`), so a full
  `"VIA AURELIA"` would not match there — one input cannot serve both formats.
- **A list-filter primitive to pick the result whose `dug` matches.** Heavier
  engine change; deferred. The ambiguity guard (decision 3) keeps the workflow
  safe without it.
- **Require a `prognaz` input for existing odonimi (SDK `--prognaz`).** A good
  future direction, but a larger change; noted, not taken now.

## Consequences

- The "odonimo exists" path works: existence is detected correctly and, for a
  unique denomination, the accesso is created on the right odonimo.
- No silent mis-write: an ambiguous denomination fails clearly instead of guessing.
- Shared-denomination odonimi (same denominazione across several `dug`) cannot be
  created through the denomination input; this is a documented limitation pending a
  `prognaz` targeting input.
- `x-concat` is reusable wherever a payload needs a composed string.
- The Bruno dry-run pair (create + suppress) becomes runnable once this lands, using
  a unique-denomination street.
