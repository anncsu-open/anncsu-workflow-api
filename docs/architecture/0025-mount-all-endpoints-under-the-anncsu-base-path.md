# 25. Mount all service endpoints under the /anncsu base path

Date: 2026-06-22

## Status

Accepted (relates to ADR 0005 versioned docs and ADR 0015 probes)

## Context

The k8s ingress routes to this service by **path prefix** and forwards the full path
unchanged (no rewrite/strip — confirmed: the app sets no `root_path`, yet the
`/anncsu/v1/...` routes are reached in cluster, so the ingress must pass the prefix
through). The intended rule routes `/anncsu` to this service.

Several endpoints lived at the **root**, outside `/anncsu`:

- the probes `/health` and `/ready` (ADR 0015),
- the root index `/`,
- the visualizer page `/workflows/ui` and the Arazzo spec served at `/workflows/spec/...`.

Under an ingress that routes only `/anncsu/*` here, those root-level paths either never
reach the service or **collide** with the identically named probes (`/health`, `/ready`)
of every other service behind the same ingress. The versioned contract was already under
`/anncsu/v1/...`, so the service base path was effectively `/anncsu` for the API but not
for the infrastructure endpoints.

## Decision

**Mount every endpoint the service exposes under the `/anncsu` base path**, so a single
ingress prefix rule routes the whole service unambiguously. A module constant
`SERVICE_PREFIX = "/anncsu"` carries the base in `app/main.py`.

- **Probes** → `/anncsu/health`, `/anncsu/ready`, kept **unversioned** (not
  `/anncsu/v1/...`). `/anncsu` is the *service mount point* (it equals the ingress path);
  `/v1` is the *API contract version*. Probes are version-independent infrastructure
  (ADR 0015), so they sit under the base but outside the versioned contract.
- **Root index** → `/anncsu`. The bare `/` now returns **404** by design: nothing routes
  to it through the ingress, and the index advertises the docs/probe entry points under
  the base path.
- **Visualizer + spec static** → `/anncsu/workflows/ui` and `/anncsu/workflows/spec/...`
  (the page's spec URL moves with the static mount, kept in lockstep).
- **Versioned contract** stays at `/anncsu/v1/...` (workflows, OpenAPI, Swagger/ReDoc) —
  unchanged.

## Consequences

- A single ingress rule (path prefix `/anncsu`) routes the entire service; the probes no
  longer collide with other services' root-level `/health`/`/ready`.
- **Breaking for deployment** (outside this repo): the k8s Deployment's
  `livenessProbe.httpGet.path` and `readinessProbe.httpGet.path` must move to
  `/anncsu/health` and `/anncsu/ready`, and any monitoring or load balancer hitting
  `/health`/`/ready` must update. The ingress rule can simplify to one `/anncsu` prefix.
- The bare `/` returns 404 by design (no root-level alias).
- `/anncsu` is hardcoded as the single base via `SERVICE_PREFIX`; if a future environment
  needs a different ingress base, promote that constant to configuration.
