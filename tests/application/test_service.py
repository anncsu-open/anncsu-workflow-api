"""Tests for ``WorkflowApplicationService``: the thin seam between routes and engine.

The service owns no domain logic (that lives in the Arazzo spec) and no transport
detail (that lives in the adapter): it runs a workflow against the injected executor
and hands back the :class:`WorkflowRun` for the route layer to present.
"""

from pathlib import Path

from app.application.service import WorkflowApplicationService
from app.executor.engine import WorkflowExecutor
from app.executor.spec import load_spec
from app.ports.transport import Response
from tests.executor.support import ScriptedTransport

SPECS_DIR = Path(__file__).resolve().parent.parent.parent / "specs"
ARAZZO_SPEC = SPECS_DIR / "anncsu-workflow.arazzo.yaml"


async def test_run_executes_the_workflow_and_returns_the_run():
    spec = load_spec(ARAZZO_SPEC)
    transport = ScriptedTransport(
        {
            "anncsu-consultazione.elencoodonimiprogPost": Response(
                200, {"data": [{"prognaz": "2000449", "dug": "VIA", "denomuff": "ROMA"}]}
            ),
            "anncsu-consultazione.elencoaccessiprogPost": Response(
                200, {"data": [{"prognazacc": "1370588", "civico": "42"}]}
            ),
        }
    )
    service = WorkflowApplicationService(WorkflowExecutor(spec, transport))

    run = await service.run(
        "ricerca-indirizzo-completo",
        {"codcom": "H501", "denom_odonimo": "ROMA", "numero_civico": "42"},
    )

    assert run.workflow_id == "ricerca-indirizzo-completo"
    assert run.outputs["odonimi"][0]["prognaz"] == "2000449"
    assert run.outputs["accessi"][0]["prognazacc"] == "1370588"
