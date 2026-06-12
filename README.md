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

Create a `.env` file in the project root:

```env
# Application
APP_NAME="ANNCSU Workflow Service"
DEBUG=false

# ANNCSU API URLs (Production)
ANNCSU_CONSULTAZIONE_URL=https://modipa.agenziaentrate.gov.it/govway/rest/in/AgenziaEntrate-PDND/anncsu-consultazione/v1
ANNCSU_ODONIMI_URL=https://modipa.agenziaentrate.it/govway/rest/in/AgenziaEntrate-PDND/anncsu-aggiornamento-odonimi/v1
ANNCSU_ACCESSI_URL=https://modipa.agenziaentrate.it/govway/rest/in/AgenziaEntrate/anncsuaccessi/v1
ANNCSU_COORDINATE_URL=https://modipa.agenziaentrate.it/govway/rest/in/AgenziaEntrate/anncsuaccessi/v1

# PDND Authentication
PDND_CLIENT_ID=your_client_id
PDND_CLIENT_SECRET=your_client_secret
PDND_TOKEN_URL=https://auth.interop.pagopa.it/token.oauth2
PDND_AUDIENCE=your_audience

# JWT Settings (per Agid-JWT-Signature e Agid-JWT-TrackingEvidence)
JWT_PRIVATE_KEY_PATH=./keys/private_key.pem
JWT_ALGORITHM=RS256

# Tracking Evidence (Audit)
USER_ID=your_user_id
USER_LOCATION=your_location
LOA=3

# Environment
USE_VALIDATION_ENV=false  # true to use the validation environment
```

### Generating JWT keys

To generate the required RSA keys:

```bash
mkdir -p keys
# Generate private key
openssl genrsa -out keys/private_key.pem 2048
# Generate public key
openssl rsa -in keys/private_key.pem -pubout -out keys/public_key.pem
```

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

```bash
# Regenerate docs/workflows.md from the Arazzo spec (clones the pinned apitapviz)
bash scripts/gen-docs.sh

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
- **Swagger UI**: http://localhost:8000/v1/docs
- **ReDoc**: http://localhost:8000/v1/redoc
- **OpenAPI**: http://localhost:8000/v1/openapi.json

The OpenAPI document is served in English by default; request another language with the
`lang` query parameter or the `Accept-Language` header, e.g.
`http://localhost:8000/v1/openapi.json?lang=it`.

## Available Workflows

Each public Arazzo workflow is exposed as a typed route under `/v1/workflows/<workflowId>`.
The call is synchronous: the response carries the workflow outcome in-band. Failures are
reported as RFC 7807 Problem Details (`application/problem+json`): a step failing its
success criteria maps to `422`, an upstream transport failure to `502` (see
`docs/architecture/0008-error-handling-at-the-operation-boundary.md`). The reusable
`sopprimi-accesso` sub-workflow is not exposed; only the executor invokes it.

### 1. Verify and Create Complete Address

Creates a complete address, first verifying the existence of the odonimo and the accesso.

**Endpoint**: `POST /v1/workflows/verifica-e-crea-indirizzo-completo`

```json
{
  "codcom": "H501",
  "denom_odonimo": "ROMA",
  "dug": "VIA",
  "numero_civico": "42",
  "data_validita": "08/10/2024"
}
```

### 2. Update Access Coordinates

Updates the geographic (GPS) coordinates of an existing accesso.

**Endpoint**: `POST /v1/workflows/aggiorna-coordinate-accesso`

```json
{
  "codcom": "H501",
  "denom_odonimo": "ROMA",
  "numero_civico": "42",
  "coordinata_x": "13.1022000",
  "coordinata_y": "41.8847600",
  "coordinata_z": "150",
  "metodo": "4"
}
```

### 3. Suppress Complete Odonimo

Suppresses an existing odonimo. Every accesso of the odonimo is suppressed first with
an explicit, traceable call (the executor iterates the `sopprimi-accesso` sub-workflow
as declared by `x-executor.foreach`), then the odonimo itself.

**Endpoint**: `POST /v1/workflows/sopprimi-odonimo-completo`

```json
{
  "codcom": "H501",
  "denom_odonimo": "VECCHIA STRADA",
  "data_soppressione": "08/10/2024"
}
```

### 4. Search Complete Address

Searches for addresses by odonimo and, optionally, numero civico.

**Endpoint**: `POST /v1/workflows/ricerca-indirizzo-completo`

```json
{
  "codcom": "H501",
  "denom_odonimo": "ROM",
  "numero_civico": "42"
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
│       └── workflows.py        # POST /v1/workflows/<workflowId> routes
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
        env:
        - name: PDND_CLIENT_ID
          valueFrom:
            secretKeyRef:
              name: anncsu-secrets
              key: client-id
```

## Troubleshooting

### Common errors

**Error: "Invalid JWT"**
- Verify that the JWT keys have been generated correctly
- Check that `JWT_PRIVATE_KEY_PATH` points to the correct file

**Error: "PDND Authentication Failed"**
- Verify `PDND_CLIENT_ID` and `PDND_CLIENT_SECRET`
- Check connectivity to `PDND_TOKEN_URL`

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
