# API requests (Bruno)

A [Bruno](https://www.usebruno.com/) collection with the probe requests validated
against a running instance.

Open the `docs/api` folder in the Bruno app, or run it headless with the CLI
(start the service first — see the repository README):

    npx @usebruno/cli run docs/api --env Local

Set the target in `environments/Local.bru` (`baseUrl`, default
`http://localhost:8000`).

- **Liveness** — `GET /health` (process up; no external dependency)
- **Readiness** — `GET /ready` (PDND voucher across all four sources)
