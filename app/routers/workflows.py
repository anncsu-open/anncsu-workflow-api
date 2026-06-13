"""Workflow execution routes: one typed ``POST /v1/workflows/<workflowId>`` per
public Arazzo workflow.

The published FastAPI contract (typed I/O models, localized via ADR 0005) is the
conformance gate over the canonical Arazzo spec: each route validates input with
the Phase A models, runs the workflow synchronously ([BLOCK_REST]), and maps the
run's declared outputs onto the typed Output model. The reusable
``sopprimi-accesso`` sub-workflow is intentionally not exposed — only the
executor invokes it (via ``x-executor.foreach``).
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.adapters.anncsu import AnncsuClientManager, AnncsuSdkTransport
from app.application.service import WorkflowApplicationService
from app.config import settings
from app.errors import PROBLEM_CONTENT_TYPE, Problem
from app.executor.engine import WorkflowExecutor
from app.executor.spec import load_spec
from app.models.workflows import (
    AggiornaAccessoDaProgressivoInput,
    AggiornaAccessoOutput,
    AggiornaCoordinateDaProgressivoAccessoInput,
    AggiornaCoordinateOutput,
    CreaIndirizzoCompletoInput,
    CreaIndirizzoCompletoOutput,
    RicercaIndirizzoInput,
    RicercaIndirizzoOutput,
    SopprimiOdonimoInput,
    SopprimiOdonimoOutput,
)

SPECS_DIR = Path(__file__).resolve().parent.parent.parent / "specs"
ARAZZO_SPEC = SPECS_DIR / "anncsu-workflow.arazzo.yaml"

COMPLETED_MESSAGE = "Workflow completed"


def _problem_response(description: str) -> dict[str, Any]:
    return {
        "description": description,
        "content": {PROBLEM_CONTENT_TYPE: {"schema": Problem.model_json_schema()}},
    }


# The RFC 7807 failures every workflow route can answer with (ADR 0008).
PROBLEM_RESPONSES: dict[int | str, dict[str, Any]] = {
    422: _problem_response(
        "Invalid request payload, or a workflow step failed its success criteria"
    ),
    500: _problem_response("Workflow execution error"),
    502: _problem_response("The upstream ANNCSU call failed before an HTTP outcome"),
}

router = APIRouter(prefix="/v1/workflows", tags=["workflows"], responses=PROBLEM_RESPONSES)


@cache
def _default_service() -> WorkflowApplicationService:
    transport = AnncsuSdkTransport(AnncsuClientManager.from_settings(settings))
    return WorkflowApplicationService(WorkflowExecutor(load_spec(ARAZZO_SPEC), transport))


def get_workflow_service() -> WorkflowApplicationService:
    """Dependency provider; tests override it to inject a scripted transport."""
    return _default_service()


ServiceDep = Annotated[WorkflowApplicationService, Depends(get_workflow_service)]


@router.post(
    "/verifica-e-crea-indirizzo-completo",
    response_model=CreaIndirizzoCompletoOutput,
    summary="Verify and create a complete address",
)
async def verifica_e_crea_indirizzo_completo(
    payload: CreaIndirizzoCompletoInput,
    service: ServiceDep,
) -> CreaIndirizzoCompletoOutput:
    """Upsert odonimo and accesso, returning the coalesced progressivi."""
    run = await service.run("verifica-e-crea-indirizzo-completo", payload.model_dump())
    return CreaIndirizzoCompletoOutput(
        success=True,
        # x-executor.coalesce resolves the progressivo from whichever branch ran.
        progressivo_nazionale_odonimo=run.outputs.get("progressivo_nazionale"),
        progressivo_civico=run.outputs.get("progressivo_civico"),
        message=COMPLETED_MESSAGE,
    )


@router.post(
    "/aggiorna-coordinate-da-progressivo-accesso",
    response_model=AggiornaCoordinateOutput,
    summary="Update the coordinates of an accesso by its national progressive",
)
async def aggiorna_coordinate_da_progressivo_accesso(
    payload: AggiornaCoordinateDaProgressivoAccessoInput,
    service: ServiceDep,
) -> AggiornaCoordinateOutput:
    """Update coordinates addressing the accesso directly (no searches, ADR 0009)."""
    run = await service.run("aggiorna-coordinate-da-progressivo-accesso", payload.model_dump())
    return AggiornaCoordinateOutput(
        success=True,
        progressivo_civico=payload.prognazacc,
        coordinate=run.outputs.get("risultato"),
        message=COMPLETED_MESSAGE,
    )


@router.post(
    "/aggiorna-accesso-da-progressivo",
    response_model=AggiornaAccessoOutput,
    summary="Update an accesso by its national progressives",
    description=(
        "Generic accesso update (ANNCSU operation R) addressed by the odonimo and "
        "accesso national progressives. Replace semantics: the request describes the "
        "accesso's new state and attributes left out are not guaranteed preserved — "
        "read the accesso first and send the full desired state."
    ),
)
async def aggiorna_accesso_da_progressivo(
    payload: AggiornaAccessoDaProgressivoInput,
    service: ServiceDep,
) -> AggiornaAccessoOutput:
    """Replace the accesso's state (no searches; unset fields stay off the wire)."""
    run = await service.run("aggiorna-accesso-da-progressivo", payload.model_dump())
    return AggiornaAccessoOutput(
        success=True,
        prognazacc=payload.prognazacc,
        accesso=run.outputs.get("risultato"),
        message=COMPLETED_MESSAGE,
    )


@router.post(
    "/sopprimi-odonimo-completo",
    response_model=SopprimiOdonimoOutput,
    summary="Suppress an odonimo and its accessi",
)
async def sopprimi_odonimo_completo(
    payload: SopprimiOdonimoInput,
    service: ServiceDep,
) -> SopprimiOdonimoOutput:
    """Suppress every accesso first (x-executor.foreach), then the odonimo."""
    run = await service.run("sopprimi-odonimo-completo", payload.model_dump())
    return SopprimiOdonimoOutput(
        success=True,
        odonimo_soppresso=run.outputs.get("odonimo_soppresso"),
        progressivo_nazionale=run.outputs.get("progressivo_nazionale"),
        accessi_presenti=run.outputs.get("accessi_presenti"),
        message=COMPLETED_MESSAGE,
    )


@router.post(
    "/ricerca-indirizzo-completo",
    response_model=RicercaIndirizzoOutput,
    summary="Search a complete address",
)
async def ricerca_indirizzo_completo(
    payload: RicercaIndirizzoInput,
    service: ServiceDep,
) -> RicercaIndirizzoOutput:
    """Read-only search of odonimi and accessi."""
    run = await service.run("ricerca-indirizzo-completo", payload.model_dump())
    return RicercaIndirizzoOutput(
        success=True,
        odonimi=run.outputs.get("odonimi") or [],
        accessi=run.outputs.get("accessi") or [],
        message=COMPLETED_MESSAGE,
    )
