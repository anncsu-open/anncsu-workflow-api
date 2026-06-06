# 2. Arazzo as the canonical workflow contract

Date: 2026-06-04

## Status

Accepted

## Context

The ANNCSU service orchestrates several multi-step business processes (upsert of a
complete address, coordinate update, odonimo suppression, address search) on top of
four separate ANNCSU OpenAPI surfaces (consultazione, odonimi, accessi, coordinate).

Without a single source of truth, that orchestration logic risks living only inside
imperative service code, where it is hard to review, hard to validate automatically,
and invisible to non-developers. We needed a way to describe *which* operations run,
*in what order*, *with which inputs/outputs*, and *under which branching conditions* —
declaratively, and decoupled from the implementation language.

The [Arazzo Specification](https://spec.openapis.org/arazzo/latest.html) is the OpenAPI
Initiative's standard for exactly this: it expresses sequences of API calls across one
or more OpenAPI descriptions, with typed inputs/outputs, success criteria, and
conditional flow.

A first attempt produced a "clean-looking" spec that turned out **not** to be valid
Arazzo 1.0: it used `dependsOn`/`when` at the step level, `info.contact`, and inline
step merges with ternaries — none of which exist in the specification. A validation
spike with Redocly CLI surfaced these errors and forced a rewrite onto legal constructs.

Tooling options were evaluated:
- **Redocly CLI** (`@redocly/cli`) — validates Arazzo against the spec, runs in Node,
  integrates cleanly into pre-commit and CI.
- **arazzo-runner** — couples validation to synchronous execution; rejected, the
  execution model is decided separately (see ADR 0003).
- **Specmatic** — commercial; rejected.

## Decision

We adopt the **Arazzo 1.0 specification** (`specs/anncsu-workflow.arazzo.yaml`) as the
canonical, machine-readable contract for the ANNCSU workflows. Service code,
documentation, and the workflow visualizer all derive from this single artifact.

The spec is written using only legal Arazzo 1.0 constructs:
- steps within a workflow are **sequential** in array order;
- conditional branching is expressed with `onSuccess`/`onFailure` + `criteria` and
  `goto`/`end` actions (the "exists → search, else → create" pattern), not `when`/`dependsOn`;
- the four ANNCSU OpenAPI documents are referenced via `sourceDescriptions`, and steps
  bind to them through `operationId`.

Where a workflow needs orchestration that Arazzo 1.0 cannot express (output coalescing
across alternative branches, for-each iteration), the requirement is **not** smuggled
into imperative code silently: it is declared explicitly in an `x-executor` extension
block on the workflow. The contract stays complete and reviewable; the executor that
fulfils the `x-executor` semantics is the subject of ADR 0003.

Validation is enforced with **Redocly CLI** (the `recommended` ruleset, configured in
`redocly.yaml`) as a **blocking gate** in both pre-commit (`.pre-commit-config.yaml`)
and CI (`.github/workflows/ci.yml`). A change that breaks the spec cannot be merged.

## Consequences

Easier:
- A single, versioned, validated contract describes every workflow; reviews focus on
  the spec rather than on scattered code paths.
- Documentation is generated from the spec (apitapviz → `docs/workflows.md` → Zensical
  site), so the published graph cannot silently drift from the contract.
- The same artifact feeds the runtime workflow visualizer, keeping design and runtime
  views aligned.
- Onboarding and domain review are open to non-developers, since the contract is
  declarative YAML.

More difficult / accepted costs:
- Arazzo 1.0's expressiveness is limited: branch coalescing and iteration cannot be
  stated in pure Arazzo, so they leak into the `x-executor` extension. That extension is
  non-standard and only meaningful to our executor (ADR 0003).
- Validation requires a Node toolchain (Redocly) alongside the Python stack, both in
  pre-commit and CI.
- The spec is pinned to Arazzo 1.0.0; a future migration to 1.1 would be a deliberate,
  separate decision.
- Domain step descriptions are in Italian (source content), so `docs/` is excluded from
  the English-only prose gate.
