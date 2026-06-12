"""Route serving an interactive UI (arazzo-ui) for the Arazzo specification.

The UI is the React component `@jentic/arazzo-ui` loaded via esm.sh (CDN) and mounted
in a page we serve; it points at the Arazzo spec served under `/workflows/spec`
(StaticFiles in `app.main`), so it resolves the relative sourceDescriptions.

Note: arazzo-ui is alpha and loading depends on the esm.sh CDN (it needs network and
does not work offline). For offline/stable use, the bundle can be vendored (npm build).
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["visualizer"])

# Versions pinned for reproducible rendering.
ARAZZO_UI_VERSION = "1.0.0-alpha.31"
REACT_VERSION = "18.3.1"  # reactflow@11 is tested on React 18

# Same-origin URL of the spec served by app.main via StaticFiles.
SPEC_URL = "/workflows/spec/anncsu-workflow.arazzo.yaml"

_PAGE = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ANNCSU — Arazzo Workflows</title>
  <link rel="stylesheet" href="https://esm.sh/@jentic/arazzo-ui@{ARAZZO_UI_VERSION}/styles.css" />
  <style>
    html, body, #root {{ height: 100%; margin: 0; }}
    #fallback {{ font-family: system-ui, sans-serif; padding: 1rem; color: #555; }}
  </style>
</head>
<body>
  <div id="root"><div id="fallback">Loading the Arazzo UI from esm.sh…</div></div>
  <script type="module">
    // esm.sh: `?deps=` forces a single shared React instance with the arazzo-ui bundle.
    import React from "https://esm.sh/react@{REACT_VERSION}";
    import {{ createRoot }} from "https://esm.sh/react-dom@{REACT_VERSION}/client";
    import {{ ArazzoUIStandalone }} from "https://esm.sh/@jentic/arazzo-ui@{ARAZZO_UI_VERSION}/standalone?deps=react@{REACT_VERSION},react-dom@{REACT_VERSION}";

    const root = createRoot(document.getElementById("root"));
    root.render(
      React.createElement(ArazzoUIStandalone, {{ document: "{SPEC_URL}", view: "split" }})
    );
  </script>
</body>
</html>
"""


@router.get(
    "/workflows/ui",
    response_class=HTMLResponse,
    summary="Interactive Arazzo workflows UI (arazzo-ui)",
    # An HTML page for humans, not API surface: keep it out of the /v1 contract.
    include_in_schema=False,
)
async def workflows_ui() -> HTMLResponse:
    """Serve the page that mounts arazzo-ui on the ANNCSU specification."""
    return HTMLResponse(_PAGE)
