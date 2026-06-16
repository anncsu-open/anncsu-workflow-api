# 5. API internationalization and path-based versioning

Date: 2026-06-08

## Status

Accepted

## Context

The FastAPI facade (the *Pubblicazione Contratto* supporting context of ADR 0004)
exposes the workflows as REST endpoints and publishes an OpenAPI document consumed via
Swagger UI / ReDoc. Two gaps surfaced:

- **Language.** The Pydantic model field descriptions were written in Italian, mixed into
  an otherwise English codebase. Project policy is English-only for code and docstrings,
  but the descriptions are also user-facing API documentation: ANNCSU consumers are
  Italian public administrations, so Italian text has real value too. We need English as
  the baseline and a way to serve the documentation in other languages without forking the
  models.
- **Versioning.** The API has no version in its paths. ANNCSU operations evolve, and we
  need a stable contract boundary so breaking changes do not silently affect existing
  clients.

## Decision

### Internationalization (i18n)

- **English is the in-code baseline.** Every Pydantic `Field(description=...)` holds an
  English string. The default `/openapi.json` is therefore English even with no catalog
  processing, and the English-only code policy holds.
- **Translation catalog.** Non-baseline languages live in `app/i18n/locales/<lang>.json`,
  each a flat map keyed by `"<SchemaName>.<field>"` → translated text (e.g.
  `"CreaIndirizzoCompletoInput.codcom"`). The current Italian descriptions are repurposed
  as the first catalog (`it.json`) rather than discarded.
- **Localized OpenAPI.** A custom OpenAPI builder walks `components.schemas.*.properties.*`
  in the generated schema and overlays the requested language's descriptions by
  `SchemaName.field` key. It uses the schema structure, not fragile text matching. Missing
  keys and unsupported languages fall back to the in-code English.
- **Language selection.** The requested language is resolved from the `lang` query
  parameter first, then the `Accept-Language` header; the default is English. This applies
  to the OpenAPI endpoint (and the docs UIs that load it).

### Versioning

- **Path-based versioning.** The API surface is mounted under `/v1`. Domain endpoints
  (the workflow-execution routes introduced with the executor facade) live under
  `/anncsu/v1/...`. Operational/tooling endpoints that are not part of the contract — the health
  check and the Arazzo visualizer — stay unversioned.
- A future breaking change introduces `/v2` served alongside `/v1`; `info.version` in the
  OpenAPI document continues to track the document's semantic version.

## Consequences

Easier:
- The codebase and the default contract are English, consistent with policy, while the
  Italian text is preserved and served on demand — no model is forked per language.
- Adding a language is a new `locales/<lang>.json` file plus a supported-languages entry;
  no code or model changes.
- `/v1` gives clients a stable contract boundary and a clear place to evolve the API.

More difficult / accepted costs:
- The OpenAPI document is no longer a single static artifact: a custom builder runs per
  requested language, and translation keys must stay aligned with schema/component names
  (a renamed model or field requires a catalog update). A test guards key alignment.
- Translations can drift from the English baseline; the catalog must be maintained as
  fields change.
- Versioned paths add a prefix the routers and tests must account for, and supporting
  multiple live versions later means maintaining more than one route set.

## Update (2026-06-13): free-text localization

The overlay was extended beyond schema field descriptions to the contract's
**free text** — operation `summary`/`description` and request-example `summary` —
keyed by the **English source string** (gettext-style) rather than a structural
key. The catalog therefore holds two key shapes: `<Schema>.<field>` for field
descriptions and the English string itself for free text; an alignment test
validates each shape (field keys against models, free-text keys against the
generated document, to catch drift).

Known limit: **Swagger UI's own chrome** (the "Try it out", "Execute",
"Parameters", "Schema" labels, etc.) is part of the Swagger UI bundle, not the
OpenAPI document, so it is not localized by this mechanism and stays in English.
Localizing it would require a Swagger UI i18n bundle, out of scope here.
