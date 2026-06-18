# ANNCSU Workflow API

A FastAPI API that exposes the ANNCSU workflows (defined in the Arazzo specification) as REST endpoints.

## Features

- **Arazzo Workflows** - Implementation of the 4 main ANNCSU workflows
- **FastAPI** - Modern, high-performance framework for REST APIs
- **PDND Authentication** - Integration with the Piattaforma Digitale Nazionale Dati
- **Authlib** - JWT and OAuth 2.0 handling
- **Testing** - Comprehensive tests with Polyfactory and Faker
- **Type Safety** - Pydantic 2.x for data validation

## Requirements

- Python 3.11+
- uv (package manager)

## Installation

```bash
# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone the repository
cd anncsu-workflow-api

# Create virtual environment and install dependencies
# (includes the `dev` dependency group by default, PEP 735)
uv sync

# Runtime dependencies only (without development tooling)
uv sync --no-dev
```

## Configuration

Copy [`.env.example`](.env.example) to `.env` and fill in the values:

```bash
cp .env.example .env
```

The full set of variables:

```env
# Application
APP_NAME="ANNCSU Workflow Service"
DEBUG=false

# Logging
LOG_LEVEL=INFO        # DEBUG | INFO | WARNING | ERROR
LOG_FORMAT=json       # json (production) | console (development)

# ANNCSU API URLs are discovered from the voucher audience (ADR 0017), not set here.
# Collaudo serves a self-signed certificate, so disable TLS verification there
# (keep it on in production):
VERIFY_SSL=true

# PDND authentication — the SDK's ClientAssertionSettings contract (ADR 0015).
# PDND_AUDIENCE is the client assertion audience (no scheme, ends with
# /client-assertion) and MUST match the environment selected by USE_VALIDATION_ENV
# (the token endpoint is derived from it); a mismatch is rejected with PDND 015-0008.
#   production:     auth.interop.pagopa.it/client-assertion
#   validation/UAT: auth.uat.interop.pagopa.it/client-assertion
PDND_KID=your_kid
PDND_ISSUER=your_client_id
PDND_SUBJECT=your_client_id
PDND_AUDIENCE=auth.interop.pagopa.it/client-assertion
# Signing key — must match the public key registered for PDND_KID. Set exactly ONE
# of PDND_KEY_PATH (a PEM file) or PDND_PRIVATE_KEY (inline PEM, as used in collaudo).
PDND_KEY_PATH=./keys/private_key.pem

# Purpose id per API — ALL must be present (may be empty for the APIs this
# service does not use: interni and coordinate_bulk).
PDND_PURPOSE_ID_PA=your_pa_purpose_id
PDND_PURPOSE_ID_ACCESSI=your_accessi_purpose_id
PDND_PURPOSE_ID_ODONIMI=your_odonimi_purpose_id
PDND_PURPOSE_ID_COORDINATE=your_coordinate_purpose_id
PDND_PURPOSE_ID_COORDINATE_BULK=
PDND_PURPOSE_ID_INTERNI=

# ModI audit context (AUDIT_REST_02) for the write APIs:
PDND_MODI_USER_ID=your_user_id
PDND_MODI_USER_LOCATION=your_location
PDND_MODI_LOA=3
# Dedicated ModI signing key — OPTIONAL (prod only; must differ from the voucher
# key). Dev/collaudo can omit it (the voucher key is used). To enable, set:
# PDND_MODI_KID=your_modi_kid
# PDND_MODI_KEY_PATH=./keys/modi_private_key.pem

# Environment
USE_VALIDATION_ENV=false  # true → UAT token endpoint (and UAT voucher audiences)
```

### Generating the PDND keys

Generate the RSA key referenced by `PDND_KEY_PATH` (the voucher signing key); in
production the write APIs also need a separate ModI signing key for
`PDND_MODI_KEY_PATH`:

```bash
mkdir -p keys
# Voucher signing key (PDND_KEY_PATH)
openssl genrsa -out keys/private_key.pem 2048
openssl rsa -in keys/private_key.pem -pubout -out keys/public_key.pem
# Dedicated ModI signing key (PDND_MODI_KEY_PATH), required by GovWay in production
openssl genrsa -out keys/modi_private_key.pem 2048
openssl rsa -in keys/modi_private_key.pem -pubout -out keys/modi_public_key.pem
```

### Logging

The service emits **structured logs** via [structlog](https://www.structlog.org/)
(ADR 0014). `LOG_FORMAT=json` renders one JSON object per line for log
aggregation; `LOG_FORMAT=console` renders a human-readable line handy under
`--reload` (colorized when stdout is a terminal, plain when redirected or in CI). `LOG_LEVEL` sets the threshold — per-step (`workflow.step`) and
per-dispatch (`transport.dispatch`) events are `DEBUG`; request boundaries
(`request.start`/`request.end`) and handled failures are `INFO`/`WARNING`/`ERROR`.

Every request carries a **correlation id**: an inbound `X-Request-ID` is reused
(otherwise one is generated), bound to the logging context for the whole run,
echoed on the `X-Request-ID` response header, and surfaced as `request_id` on the
RFC 7807 Problem body. Sensitive keys (authorization, tokens, JWT/assertions,
secrets, private keys) are masked by a central redaction processor, and request
payloads are never logged.

### Health and readiness

Two probes are exposed (ADR 0015):

- `GET /health` — **liveness**: returns `200 {"status": "ok"}` whenever the
  process is up, with no external dependency, so an orchestrator never restarts
  the pod over a transient PDND blip.
- `GET /ready` — **readiness**: confirms every Arazzo source can obtain a PDND
  voucher (cached, refreshed only near expiry). Returns `200` with a per-source
  token TTL when all four authenticate, or `503` otherwise.

PDND auth is built once at startup (the lifespan): a misconfigured `PDND_*`
environment fails fast, while access tokens are fetched lazily on first use and
refreshed automatically.

### Inbound security (ADR 0023)

The workflow routes (`/anncsu/v1/workflows/*`) are guarded for machine-to-machine
callers; the probes (`/health`, `/ready`), the docs/OpenAPI, the root, and the
visualizer stay open. The guard checks, in order:

1. **API-KEY** — the `X-API-KEY` header must equal `API_KEY` (advertised as an
   `apiKey` security scheme in the OpenAPI). `API_KEY` is **required**: without it
   every protected call is rejected with `401`.
2. **Source-IP ACL** — the caller IP (from `X-Real-IP`, set by the ingress, else the
   socket peer) must fall within `ALLOWED_IPS` (comma-separated CIDR). Outside → `403`.
3. **Hostname ACL** — the called host must be in `ALLOWED_FQDN`. Not allowed → `403`.

`ALLOWED_IPS`/`ALLOWED_FQDN` are enforced only when set; leave them empty to skip
that dimension. The API-KEY is accepted **only on the private ingress** by listing
that ingress's FQDN in `ALLOWED_FQDN` (the public ingress carries a different host
and is rejected). `X-Real-IP` is trusted because the ingress sets it, so the service
must be reachable only through the ingress in production. Rejections are RFC 7807
Problems; the API-KEY value is never logged.

## Testing

### Run all tests

```bash
uv run pytest
```

### With coverage

```bash
uv run pytest --cov=app --cov-report=html
```

### Specific tests

```bash
# Models tests only
uv run pytest tests/test_models.py

# Verbose tests with detailed output
uv run pytest -v

# Tests with markers
uv run pytest -m "not slow"
```

### Testing using the factories

The Polyfactory factories automatically generate consistent test data:

```python
from tests.factories import CreaIndirizzoCompletoInputFactory

# Generate a single model
indirizzo = CreaIndirizzoCompletoInputFactory.build()

# Generate a batch of models
indirizzi = CreaIndirizzoCompletoInputFactory.batch(10)

# Override specific fields
indirizzo = CreaIndirizzoCompletoInputFactory.build(
    codcom="H501",
    denom_odonimo="ROMA"
)
```

## Linting and Formatting

```bash
# Linting
uv run ruff check .

# Auto-fix
uv run ruff check --fix .

# Formatting
uv run ruff format .

# Type checking (using Astral's Ty)
uv tool install ty  # One-time installation
ty check app/       # Check on app
ty check tests/     # Check on tests
ty check .          # Check on the whole project
```

## Validating the Arazzo specification

The `specs/anncsu-workflow.arazzo.yaml` specification is validated with **Redocly CLI**
(the `recommended` ruleset, configured in `redocly.yaml`). It requires Node.

```bash
# Manual validation
npx @redocly/cli@2.31.5 lint "specs/anncsu-workflow.arazzo.yaml"
```

Validation is a **blocking gate** both in pre-commit and in CI.

### Pre-commit

```bash
# Hook installation (one-time)
prek install

# Run on all files
prek run --all-files
```

Active hooks: `ruff check`, `ruff format` and `ty` type checking (via `uv run`, aligned with
the versions in `pyproject.toml`), Arazzo validation (Redocly, in a Node environment managed
by prek), and the English-only prose check (Vale).

### English-only prose (Vale)

The README and all Python docstrings/comments must be written in English. This is
enforced with [Vale](https://vale.sh) (config in `.vale.ini`): a custom rule flags
Italian text, while ANNCSU domain terms (odonimo, accesso, civico, codcom, …) are
whitelisted in the `ANNCSU` vocabulary (`.vale/styles/config/vocabularies/ANNCSU/accept.txt`).
Code blocks are ignored. The check is a **blocking gate** in pre-commit and CI.

Vale is a standalone binary; install it locally to run the pre-commit hook:

```bash
brew install vale          # macOS
vale README.md app tests   # run manually
```

### CI

The `.github/workflows/ci.yml` workflow runs on push/PR: `uv sync`,
ruff lint + format check, `ty` type checking, blocking Arazzo validation,
the English-only Vale check, and `pytest --cov=app`.

## Documentation site (Zensical)

A static documentation site is built with [Zensical](https://zensical.org)
(config in `zensical.toml`). The workflows page (`docs/workflows.md`) is generated
from the Arazzo spec with [apitapviz](https://github.com/lornajane/apitapviz) and
includes a Mermaid graph of the flow (rendered natively by Zensical).

The **API reference** page (`docs/api/`) embeds Swagger UI over the `/v1` OpenAPI
contract. The contract JSONs (one per language) are exported from the code by
`scripts/export_openapi.py` at every docs build — they are build artifacts, not
committed — so the published Swagger always reflects the code on `main`.

```bash
# Regenerate docs/workflows.md from the Arazzo spec (clones the pinned apitapviz)
bash scripts/gen-docs.sh

# Export the /v1 OpenAPI contracts for the API reference page
uv run python scripts/export_openapi.py

# Build the static site into site/
uv run zensical build

# Live preview
uv run zensical serve
```

The generated page reflects the spec's step descriptions, which are domain content
and may be in Italian; `docs/` is therefore excluded from the English-only Vale check.

## Starting the service

```bash
# Development
uv run uvicorn app.main:app --reload

# Production
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The service will be available at `http://localhost:8000`

Interactive documentation (the API contract is published under `/v1`, see
`docs/architecture/0005-api-internationalization-and-versioning.md`):
- **Swagger UI**: http://localhost:8000/anncsu/v1/docs
- **ReDoc**: http://localhost:8000/anncsu/v1/redoc
- **OpenAPI**: http://localhost:8000/anncsu/v1/openapi.json

The OpenAPI document is served in English by default; request another language with the
`lang` query parameter or the `Accept-Language` header, e.g.
`http://localhost:8000/anncsu/v1/openapi.json?lang=it`.

## Available Workflows

Each public Arazzo workflow is exposed as a typed route under `/anncsu/v1/workflows/<workflowId>`.
The call is synchronous: the response carries the workflow outcome in-band. Failures are
reported as RFC 7807 Problem Details (`application/problem+json`): a step failing its
success criteria maps to `422`, an upstream transport failure to `502` (see
`docs/architecture/0008-error-handling-at-the-operation-boundary.md`). The reusable
`sopprimi-accesso` sub-workflow is not exposed; only the executor invokes it.

### 1. Verify and Create Complete Address

Creates a complete address, first verifying the existence of the odonimo and the accesso.

**Endpoint**: `POST /anncsu/v1/workflows/verifica-e-crea-indirizzo-completo`

```json
{
  "codcom": "H501",
  "denom_odonimo": "ROMA",
  "dug": "VIA",
  "numero_civico": "42",
  "data_validita": "08/10/2024",
  "sezione_censimento": "580911010001"
}
```

The `sezione_censimento` (ISTAT `SEZ21_ID` format) is required: ANNCSU needs it
to create the accesso and it cannot be derived from the consultation APIs.

The existence check sends ANNCSU the full street name (`dug` + `denom_odonimo`,
e.g. `VIA AURELIA`), which is what `esisteOdonimo` requires (ADR 0019). When the
odonimo already exists, the denomination must be **unique within the municipality**:
if it is shared across several `dug` (e.g. CIRCONVALLAZIONE / RAMPA / VIA "AURELIA")
the workflow fails rather than guess which one to extend — targeting a specific
odonimo by `prognaz` is a possible future addition.

### 2. Update an Accesso by National Progressives

The single endpoint for every accesso change — attributes and/or coordinates —
addressed by the odonimo and accesso national progressives. It is a **patch via
read-modify-write** (see
`docs/architecture/0012-unify-accesso-update-via-read-modify-write.md`): the
workflow reads the current accesso and the fields you send override it, so
unspecified fields are preserved without the caller having to know them. A
**coordinate-only** update therefore sends just the coordinates.

`sezione_censimento` is **always required**: it is mandatory for the update and
is not exposed by the consultation API, so it cannot be recovered by the read.
Coordinates, when sent, are validated up front (decimal WGS84 within the Italy
bounds x 6.0–18.0 / y 36.0–47.0, co-dependent — x and y together — survey
`metodo` 1–4); `numero` and `metrico` are mutually exclusive.

**Endpoint**: `POST /anncsu/v1/workflows/aggiorna-accesso-da-progressivo`

```json
{
  "codcom": "H501",
  "prognaz": "2000449",
  "prognazacc": "1370588",
  "sezione_censimento": "580911010001",
  "coordinata_x": "13.1022000",
  "coordinata_y": "41.8847600"
}
```

### 3. Update an Odonimo by National Progressive

Updates an odonimo (ANNCSU operation R) addressed by its national progressive. Same
**patch via read-modify-write** as the accesso update (see
`docs/architecture/0013-odonimo-update-by-progressive.md`): the workflow reads the
current odonimo and the fields you send override it, so unspecified fields are
preserved. `denom_delibera` is **always required** — it is the odonimo's denomination
and is not exposed by the consultation API, so it cannot be recovered by the read. The
optional `provvedimento` (delibera flag `0`–`4`; `0`/`1` require `data` + `protocollo`)
and `aut_prefettura` (`data_pref` and `protocollo_pref` co-required) are validated up front.

**Endpoint**: `POST /anncsu/v1/workflows/aggiorna-odonimo-da-progressivo`

```json
{
  "codcom": "H501",
  "prognaz": "2000449",
  "denom_delibera": "VIA ROMA",
  "denom_localita": "CENTRO STORICO"
}
```

### 4. Suppress Complete Odonimo

Suppresses an existing odonimo. Every accesso of the odonimo is suppressed first with
an explicit, traceable call (the executor iterates the `sopprimi-accesso` sub-workflow
as declared by `x-executor.foreach`), then the odonimo itself.

**Endpoint**: `POST /anncsu/v1/workflows/sopprimi-odonimo-completo`

```json
{
  "codcom": "H501",
  "denom_odonimo": "VECCHIA STRADA",
  "data_soppressione": "08/10/2024"
}
```

### 5. Suppress a Single Accesso

Suppresses one accesso (a single civico) addressed by the odonimo and accesso
national progressives, without touching the odonimo. A dated logical suppression
(ANNCSU operation S). This is the same workflow the odonimo suppression iterates
internally, also available standalone.

**Endpoint**: `POST /anncsu/v1/workflows/sopprimi-accesso`

```json
{
  "codcom": "H501",
  "prognaz": "2000449",
  "prognazacc": "1370588",
  "data_soppressione": "08/10/2024"
}
```

### 6. Search Complete Address

Searches for addresses by odonimo and, optionally, numero civico. The odonimo is
located either by denomination (`denom_odonimo`) or directly by its national
progressive (`progressivo_nazionale`) — the two are mutually exclusive (exactly one,
ADR 0021). In progressive mode the denomination search is skipped (`prognazarea`).
When a denomination matches more than one odonimo the search returns all candidates
with an empty `accessi` list (it never silently picks the first match); re-query the
chosen one with workflow 7 (ADR 0018).

**Endpoint**: `POST /anncsu/v1/workflows/ricerca-indirizzo-completo`

```json
{
  "codcom": "H501",
  "denom_odonimo": "ROM",
  "numero_civico": "42"
}
```

By the odonimo's national progressive instead of the denomination:

```json
{
  "codcom": "H501",
  "progressivo_nazionale": "919572",
  "numero_civico": "42"
}
```

### 7. Search Accessi by Odonimo Progressive

Resolves an odonimo by its national progressive (`prognaz`) and lists the accessi
matching a filter. This is the path to target a specific odonimo and to search
metric accessi: `numero_civico` maps to ANNCSU's `accparz`, which accepts a civic
**or** a metric value (partial allowed). `accparz` is **required** by ANNCSU — there
is no unfiltered listing — so `numero_civico` is mandatory here (ADR 0018).

**Endpoint**: `POST /anncsu/v1/workflows/ricerca-accessi-per-odonimo`

```json
{
  "codcom": "H501",
  "prognaz": "907720",
  "numero_civico": "1"
}
```

### 8. Add an Accesso to an Existing Odonimo

Adds an accesso to an odonimo identified deterministically by its national
progressive (`prognaz`, required). Existence is checked from that `prognaz` with the
AdE `accparz` format `civico[/esponente][-specificità]`: no match → create; exactly
one → return the existing `prognazacc`; more than one → fail (ambiguous). It does not
create the odonimo — use workflow 1 for that. The deterministic, odonimo-already-known
counterpart of workflow 1 (ADR 0020).

**Endpoint**: `POST /anncsu/v1/workflows/crea-accesso-per-odonimo`

```json
{
  "codcom": "H501",
  "prognaz": "907720",
  "numero_civico": "42",
  "esponente": "A",
  "sezione_censimento": "580911010001"
}
```

### 9. Verify and Create an Odonimo (only)

Creates only the odonimo, after verifying it does not already exist. `esisteOdonimo`
is queried with the full name (`dug` + `denom_odonimo`); if absent it is created, if
present its national progressive is returned (ambiguous denominations are refused,
ADR 0019). No accesso is created — use workflow 8 to add one. Pairs with workflow 8 to
build an address in two deterministic steps (create the odonimo, then its accessi).

**Endpoint**: `POST /anncsu/v1/workflows/verifica-e-crea-odonimo-completo`

```json
{
  "codcom": "H501",
  "denom_odonimo": "ROMA",
  "dug": "VIA"
}
```

## Project Structure

```
anncsu-workflow-api/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI entry point (health, visualizer, /v1 routes)
│   ├── config.py               # Configuration
│   ├── errors.py               # RFC 7807 Problem Details exception handlers
│   ├── adapters/
│   │   └── anncsu/             # SDK transport adapter (registry, client manager)
│   ├── application/
│   │   └── service.py          # WorkflowApplicationService (routes -> engine)
│   ├── executor/               # Generic Arazzo engine (spec, context, expressions)
│   ├── i18n/                   # Localized OpenAPI overlay (ADR 0005)
│   ├── models/
│   │   └── workflows.py        # Pydantic I/O models (the published contract)
│   ├── ports/
│   │   └── transport.py        # WorkflowTransport port, Response, TransportError
│   └── routers/
│       ├── visualizer.py       # arazzo-ui route
│       └── workflows.py        # POST /anncsu/v1/workflows/<workflowId> routes
├── specs/                      # Arazzo spec + the 4 source OpenAPI files
├── tests/                      # Unit, route, i18n, and regression suites
├── docs/                       # Zensical docs site + architecture/ (ADRs)
├── pyproject.toml              # uv configuration
├── README.md
└── .env                        # Configuration (do not commit!)
```

The layering follows the hexagonal architecture decided in
`docs/architecture/0004-adopt-ddd-with-a-hexagonal-architecture.md`: domain flow lives in
the canonical Arazzo spec, the engine is generic, and the ANNCSU SDK sits behind the
`WorkflowTransport` port.

## Integrated ANNCSU APIs

The service integrates the following ANNCSU APIs:

1. **Consultazione** - Existence verification and search for odonimi/accessi
2. **Aggiornamento Odonimi** - Insertion, update and suppression of odonimi
3. **Aggiornamento Accessi** - Management of numeri civici
4. **Aggiornamento Coordinate** - Management of geographic coordinates

## Security

### PDND Authentication

The service implements:
- **Bearer Token JWT** (OAuth 2.0)
- **Agid-JWT-Signature** - Payload integrity (ModI)
- **Agid-JWT-TrackingEvidence** - Audit tracking (ModI)

### Implemented ModI Patterns

- `[AUDIT_REST_02]` - Forwarding of tracked data with correlation
- `[BLOCK_REST]` - Blocking REST
- `[INTEGRITY_REST_02]` - Message payload integrity

## Monitoring and Logging

The service includes:
- Structured logging
- Health check endpoint: `GET /health`
- Prometheus-compatible metrics (TODO)

## Docker

The image is built entirely on `uv` (`uv sync --frozen` + `uv run fastapi run`) and
published to the GitHub Container Registry as multi-arch (`linux/amd64`, `linux/arm64`)
by `.github/workflows/docker.yml`.

```bash
# Pull the published image (tag `latest` tracks the main branch)
docker pull ghcr.io/anncsu-open/anncsu-workflow-api:latest
docker run -p 8000:8000 --env-file .env ghcr.io/anncsu-open/anncsu-workflow-api:latest
```

```bash
# Build locally
docker build -t anncsu-workflow-api .
docker run -p 8000:8000 --env-file .env anncsu-workflow-api
```

The service listens on port `8000`; `GET /health` is used by the container healthcheck.

## Deployment

### Kubernetes

Example deployment:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: anncsu-workflow-api
spec:
  replicas: 3
  selector:
    matchLabels:
      app: anncsu-workflow-api
  template:
    metadata:
      labels:
        app: anncsu-workflow-api
    spec:
      containers:
      - name: api
        image: ghcr.io/anncsu-open/anncsu-workflow-api:latest
        ports:
        - containerPort: 8000
        envFrom:
        - secretRef:
            name: anncsu-pdnd        # provides the PDND_* / PDND_MODI_* variables
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
        readinessProbe:
          httpGet:
            path: /ready
            port: 8000
```

## Troubleshooting

### Common errors

**Error: "Invalid JWT" / signature errors**
- Verify that the RSA keys have been generated correctly
- Check that `PDND_KEY_PATH` (and `PDND_MODI_KEY_PATH` for the write APIs) point to
  the correct files

**Error: "PDND authentication failed"**
- Verify `PDND_KID`, `PDND_ISSUER`/`PDND_SUBJECT`, and the `PDND_PURPOSE_ID_*` for
  the API in use
- Ensure `PDND_AUDIENCE` matches the environment selected by `USE_VALIDATION_ENV`
- Hit `GET /ready` to see which source fails to authenticate

**Error: "ANNCSU API unreachable"**
- Verify the API URLs in `.env`
- Check firewalls and network connectivity

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

### Guidelines

- Use **Ruff** for formatting and linting
- Write tests using **Polyfactory** for the data
- Keep coverage > 80%
- Document new APIs in Swagger

## License

This project is part of the ANNCSU system of the Agenzia delle Entrate.

## Contacts

For technical support: infopdnd_anncsu@sogei.it

## References

- [Arazzo Specification](https://spec.openapis.org/arazzo/latest.html)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Polyfactory Documentation](https://polyfactory.litestar.dev/)
- [PDND - Piattaforma Digitale Nazionale Dati](https://www.interop.pagopa.it/)
- [ModI - Modello di Interoperabilità](https://www.agid.gov.it/it/infrastrutture/sistema-pubblico-connettivita/il-nuovo-modello-interoperabilita)
```
