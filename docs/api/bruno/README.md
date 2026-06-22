# API requests (Bruno)

A [Bruno](https://www.usebruno.com/) collection with the probe and workflow
requests validated against a running instance.

Open the `docs/api/bruno` folder in the Bruno app, or run it headless with the CLI
(start the service first — see the repository README):

    npx @usebruno/cli run docs/api/bruno --env Local

Set the target in `environments/Local.bru` (`baseUrl`, default
`http://localhost:8000`).

The workflow routes require an API-KEY (ADR 0023): every workflow request carries an
`X-API-KEY: {{apiKey}}` header, read from the `apiKey` environment variable — set it
in `environments/Local.bru` to match the server's `API_KEY`. The probes do not need
it. **Sicurezza - Senza API-KEY (401)** is the negative check: it sends an empty
`X-API-KEY` and expects a `401`.

Probes:

- **Liveness** — `GET /anncsu/health` (process up; no external dependency)
- **Readiness** — `GET /anncsu/ready` (PDND voucher across all four sources)

Read-only search (`POST /anncsu/v1/workflows/ricerca-indirizzo-completo`), validated
against PDND collaudo:

- **Ricerca Indirizzo Completo esistente** — odonimo with a matching civic; both
  lists populated.
- **Ricerca Indirizzo Completo Inesistente** — existing odonimo, no matching
  civic; ANNCSU 404 maps to an empty `accessi` list (200, not 422).
- **Ricerca Indirizzo Solo Odonimi** — no civic; the accessi step is skipped.
- **Ricerca Indirizzo Odonimo Inesistente** — unknown odonimo; ANNCSU 404 maps to
  both lists empty (200, not 422).
- **Ricerca Indirizzo per Progressivo** — locate the odonimo by its national
  progressive instead of the denomination (`prognazarea`); `progressivo_nazionale`
  and `denom_odonimo` are mutually exclusive (ADR 0021).

By an existing odonimo's progressive (`prognaz`), validated against PDND collaudo
(ADR 0018/0020):

- **Ricerca Accessi per Odonimo** — list a specific odonimo's accessi
  (`POST /anncsu/v1/workflows/ricerca-accessi-per-odonimo`).
- **Ricerca Accessi per Odonimo con Esponente** — filter by civic + esponente; the
  two fold into `accparz` with the AdE format `civico/esponente` (a specificità
  appends `-…`).
- **Crea Accesso per Odonimo Esistente** —
  `POST /anncsu/v1/workflows/crea-accesso-per-odonimo`: add an accesso to an existing
  odonimo (prognaz required). The example hits the already-exists branch (returns
  the existing `prognazacc`, no write); the create branch is a WRITE.

Creation (`POST /anncsu/v1/workflows/verifica-e-crea-indirizzo-completo`) — WRITE
operations; run only against collaudo (UAT), never production:

- **Crea Indirizzo Completo Civico** — civic fork (`numero_civico`).
- **Crea Indirizzo Completo Metrico** — metric fork (`metrico`); civic and metric
  are mutually exclusive (ADR 0016).

Self-cancelling "dry-run" pair — WRITE operations on collaudo; run the two in
sequence (or run the collection in order) so the overall effect is a no-op,
mirroring how the SDK exercises a write without leaving a live record:

- **Dry-run Accesso 1 Crea** — creates an accesso and stores the returned
  progressivi in collection variables.
- **Dry-run Accesso 2 Rimuovi** — suppresses exactly that accesso
  (`POST /anncsu/v1/workflows/sopprimi-accesso`). ANNCSU suppression is dated and logical,
  so a suppressed record remains (there is no true delete).
- **Dry-run Odonimo 1 Crea** — creates an odonimo with a unique,
  timestamp-suffixed denomination (so the verify step always takes the create
  branch, ADR 0019) via `POST /anncsu/v1/workflows/verifica-e-crea-odonimo-completo`; no
  accesso is created.
- **Dry-run Odonimo 2 Rimuovi** — suppresses exactly that odonimo by denomination
  (`POST /anncsu/v1/workflows/sopprimi-odonimo-completo`); the fresh odonimo has no accessi,
  so only the odonimo is suppressed.
