#!/usr/bin/env bash
# Refresh the published "API examples" page from a Bruno GUI export.
#
# Bruno's "Generate documentation" feature exports an OpenCollection HTML whose
# viewer assets are loaded from cdn.opencollection.com. We self-host those assets
# under docs/api/examples/assets/, so this script only rewrites the two CDN URLs to
# the local paths and writes the page to docs/api/examples/collection.html.
#
# Content comes from the .bru files via the GUI export — never hand-edit the
# embedded collection data. (Headless regeneration is a TODO; see the ADR backlog.)
#
# Usage: scripts/refresh-api-examples.sh <bruno-exported-docs.html>
set -euo pipefail

SRC="${1:?usage: scripts/refresh-api-examples.sh <bruno-exported-docs.html>}"
DEST="docs/api/examples/collection.html"

sed -e 's#https://cdn.opencollection.com/docs.css#assets/opencollection.css#g' \
    -e 's#https://cdn.opencollection.com/docs.js#assets/opencollection.js#g' \
    "$SRC" >"$DEST"

echo "Wrote $DEST with self-hosted assets."
