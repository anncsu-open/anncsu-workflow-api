# ANNCSU Workflow API

This site documents the [Arazzo](https://spec.openapis.org/arazzo/latest.html)
workflows for the ANNCSU address system.

- **[Arazzo workflows](workflows.md)** — generated overview of the workflows,
  their steps, and a Mermaid graph of the flow.
- **[API reference](api/index.md)** — interactive Swagger UI over the `/v1`
  OpenAPI contract, regenerated from the code at every build (English/Italiano).

The canonical workflow contract lives in `specs/anncsu-workflow.arazzo.yaml` and is
validated with Redocly. An interactive viewer (arazzo-ui) is also served by the API at
`/workflows/ui`. See the repository `README.md` for details.
