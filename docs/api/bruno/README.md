# API requests (Bruno)

A [Bruno](https://www.usebruno.com/) collection with the probe and workflow
requests validated against a running instance.

Open the `docs/api/bruno` folder in the Bruno app, or run it headless with the CLI
(start the service first — see the repository README):

    npx @usebruno/cli run docs/api/bruno --env Local

Set the target in `environments/Local.bru` (`baseUrl`, default
`http://localhost:8000`).

Probes:

- **Liveness** — `GET /health` (process up; no external dependency)
- **Readiness** — `GET /ready` (PDND voucher across all four sources)

Read-only search (`POST /v1/workflows/ricerca-indirizzo-completo`), validated
against PDND collaudo:

- **Ricerca Indirizzo Completo esistente** — odonimo with a matching civic; both
  lists populated.
- **Ricerca Indirizzo Completo Inesistente** — existing odonimo, no matching
  civic; ANNCSU 404 maps to an empty `accessi` list (200, not 422).
- **Ricerca Indirizzo Solo Odonimi** — no civic; the accessi step is skipped.
- **Ricerca Indirizzo Odonimo Inesistente** — unknown odonimo; ANNCSU 404 maps to
  both lists empty (200, not 422).

Creation (`POST /v1/workflows/verifica-e-crea-indirizzo-completo`) — WRITE
operations; run only against collaudo (UAT), never production:

- **Crea Indirizzo Completo Civico** — civic fork (`numero_civico`).
- **Crea Indirizzo Completo Metrico** — metric fork (`metrico`); civic and metric
  are mutually exclusive (ADR 0016).
