"""Workflow execution routes: one typed ``POST /v1/workflows/<workflowId>`` per
public Arazzo workflow.

The published FastAPI contract (typed I/O models, localized via ADR 0005) is the
conformance gate over the canonical Arazzo spec: each route validates input with
the Phase A models, runs the workflow synchronously ([BLOCK_REST]), and maps the
run's declared outputs onto the typed Output model. ``sopprimi-accesso`` is both
a standalone route and the workflow the odonimo-suppression ``x-executor.foreach``
invokes per accesso.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

from anncsu.common.auth import PDNDAuthManager
from anncsu.common.config import ClientAssertionSettings
from fastapi import APIRouter, Body, Depends, Request

from app.adapters.anncsu import AnncsuClientManager, AnncsuSdkTransport
from app.adapters.anncsu.auth import build_auth_managers, build_client_builders
from app.application.service import WorkflowApplicationService
from app.config import Settings, resolve_token_endpoint
from app.errors import PROBLEM_CONTENT_TYPE, Problem
from app.executor.engine import WorkflowExecutor
from app.executor.spec import load_spec
from app.models.workflows import (
    AggiornaAccessoDaProgressivoInput,
    AggiornaAccessoOutput,
    AggiornaOdonimoDaProgressivoInput,
    AggiornaOdonimoOutput,
    CreaIndirizzoCompletoInput,
    CreaIndirizzoCompletoOutput,
    RicercaAccessiPerOdonimoInput,
    RicercaIndirizzoInput,
    RicercaIndirizzoOutput,
    SopprimiAccessoInput,
    SopprimiAccessoOutput,
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


def build_workflow_service(
    settings: Settings,
    assertion_settings: ClientAssertionSettings,
    *,
    manager_factory: Callable[..., Any] = PDNDAuthManager,
) -> tuple[WorkflowApplicationService, dict[str, Any], AnncsuClientManager]:
    """Build the authenticated service, the per-source auth managers, and the manager.

    Called once from the application lifespan. No token or e-service URL is resolved
    here: each SDK client is built lazily on first use, discovering its server URL
    from the voucher audience (ADR 0017). The auth managers and the client manager
    are returned so ``/ready`` can probe each source under its per-source lock.
    """
    token_endpoint = resolve_token_endpoint(settings.use_validation_env)
    auth_managers = build_auth_managers(
        assertion_settings,
        token_endpoint=token_endpoint,
        manager_factory=manager_factory,
    )
    builders = build_client_builders(
        auth_managers, assertion_settings, verify_ssl=settings.verify_ssl
    )
    client_manager = AnncsuClientManager(builders=builders)
    transport = AnncsuSdkTransport(client_manager)
    service = WorkflowApplicationService(WorkflowExecutor(load_spec(ARAZZO_SPEC), transport))
    return service, auth_managers, client_manager


def get_workflow_service(request: Request) -> WorkflowApplicationService:
    """Resolve the lifespan-built authenticated service from app state (ADR 0015).

    Tests override this dependency to inject a scripted transport.
    """
    return request.app.state.workflow_service


ServiceDep = Annotated[WorkflowApplicationService, Depends(get_workflow_service)]


# The address creation carries one optional field (data_validita) — show both shapes.
_CREA_INDIRIZZO_EXAMPLES: dict[str, Any] = {
    "minimal": {
        "summary": "Required fields only (server dates default to today)",
        "value": {
            "codcom": "H501",
            "denom_odonimo": "ROMA",
            "dug": "VIA",
            "numero_civico": "42",
            "sezione_censimento": "580911010001",
        },
    },
    "with_validity_date": {
        "summary": "With an explicit administrative validity date",
        "value": {
            "codcom": "H501",
            "denom_odonimo": "ROMA",
            "dug": "VIA",
            "numero_civico": "42",
            "sezione_censimento": "580911010001",
            "data_validita": "08/10/2024",
        },
    },
    "metric_access": {
        "summary": "A metric accesso (no civic number; skips the civic existence check)",
        "value": {
            "codcom": "H501",
            "denom_odonimo": "ROMA",
            "dug": "VIA",
            "metrico": "300",
            "sezione_censimento": "580911010001",
        },
    },
    "with_coordinates_and_attributes": {
        "summary": "Civic accesso with coordinates and optional attributes",
        "value": {
            "codcom": "H501",
            "denom_odonimo": "ROMA",
            "dug": "VIA",
            "numero_civico": "42",
            "esponente": "A",
            "sezione_censimento": "580911010001",
            "coordinata_x": "13.1022000",
            "coordinata_y": "41.8847600",
            "coordinata_z": "150",
            "metodo": "3",
        },
    },
    "with_odonimo_metadata": {
        "summary": "With odonimo metadata and an explicit delibera",
        "value": {
            "codcom": "H501",
            "denom_odonimo": "ROMA",
            "dug": "VIA",
            "numero_civico": "42",
            "sezione_censimento": "580911010001",
            "denom_localita": "CENTRO",
            "denom_delibera": "VIA ROMA",
            "provvedimento": {"flag_delibera": "1", "data": "01/01/2024", "protocollo": "PROT/123"},
        },
    },
}


@router.post(
    "/verifica-e-crea-indirizzo-completo",
    response_model=CreaIndirizzoCompletoOutput,
    summary="Verify and create a complete address",
)
async def verifica_e_crea_indirizzo_completo(
    payload: Annotated[CreaIndirizzoCompletoInput, Body(openapi_examples=_CREA_INDIRIZZO_EXAMPLES)],
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


# Named request examples for the unified accesso update (the OpenAPI carries them
# so the docs show the supported input shapes — ADR 0012).
_ACCESSO_UPDATE_EXAMPLES: dict[str, Any] = {
    "coordinates_only": {
        "summary": "Coordinates only (attributes preserved by the read)",
        "value": {
            "codcom": "H501",
            "prognaz": "2000449",
            "prognazacc": "1370588",
            "sezione_censimento": "580911010001",
            "coordinata_x": "13.1022000",
            "coordinata_y": "41.8847600",
            "metodo": "4",
        },
    },
    "attribute_only": {
        "summary": "One attribute (coordinates preserved by the read)",
        "value": {
            "codcom": "H501",
            "prognaz": "2000449",
            "prognazacc": "1370588",
            "sezione_censimento": "580911010001",
            "esponente": "A",
        },
    },
    "mixed": {
        "summary": "Attributes and coordinates together",
        "value": {
            "codcom": "H501",
            "prognaz": "2000449",
            "prognazacc": "1370588",
            "sezione_censimento": "580911010001",
            "esponente": "A",
            "specificita": "ROSSO",
            "coordinata_x": "13.1022000",
            "coordinata_y": "41.8847600",
        },
    },
}


@router.post(
    "/aggiorna-accesso-da-progressivo",
    response_model=AggiornaAccessoOutput,
    summary="Update an accesso by its national progressives",
    description=(
        "Update an accesso (ANNCSU operation R) addressed by the odonimo and accesso "
        "national progressives. Patch via read-modify-write: the workflow reads the "
        "current accesso and the fields you send override it, so unspecified fields "
        "are preserved. `sezione_censimento` is not exposed by the consultation API, "
        "so it is always required. Coordinate-only updates send just the coordinates."
    ),
)
async def aggiorna_accesso_da_progressivo(
    payload: Annotated[
        AggiornaAccessoDaProgressivoInput, Body(openapi_examples=_ACCESSO_UPDATE_EXAMPLES)
    ],
    service: ServiceDep,
) -> AggiornaAccessoOutput:
    """Read the accesso, overlay the provided fields, write the R replace."""
    run = await service.run("aggiorna-accesso-da-progressivo", payload.model_dump())
    return AggiornaAccessoOutput(
        success=True,
        prognazacc=payload.prognazacc,
        accesso=run.outputs.get("risultato"),
        message=COMPLETED_MESSAGE,
    )


# Named request examples for the odonimo update (ADR 0013).
_ODONIMO_UPDATE_EXAMPLES: dict[str, Any] = {
    "locality_only": {
        "summary": "Update the locality (other fields preserved by the read)",
        "value": {
            "codcom": "H501",
            "prognaz": "2000449",
            "denom_delibera": "VIA ROMA",
            "denom_localita": "CENTRO STORICO",
        },
    },
    "with_delibera": {
        "summary": "Denomination with an authorizing delibera",
        "value": {
            "codcom": "H501",
            "prognaz": "2000449",
            "denom_delibera": "VIA ROMA",
            "dug": "VIA",
            "provvedimento": {"flag_delibera": "1", "data": "01/01/2024", "protocollo": "PROT/123"},
        },
    },
}


@router.post(
    "/aggiorna-odonimo-da-progressivo",
    response_model=AggiornaOdonimoOutput,
    summary="Update an odonimo by its national progressive",
    description=(
        "Update an odonimo (ANNCSU operation R) addressed by its national progressive. "
        "Patch via read-modify-write: the workflow reads the current odonimo and the "
        "fields you send override it, so unspecified fields are preserved. "
        "`denom_delibera` is not exposed by the consultation API, so it is always required."
    ),
)
async def aggiorna_odonimo_da_progressivo(
    payload: Annotated[
        AggiornaOdonimoDaProgressivoInput, Body(openapi_examples=_ODONIMO_UPDATE_EXAMPLES)
    ],
    service: ServiceDep,
) -> AggiornaOdonimoOutput:
    """Read the odonimo, overlay the provided fields, write the R replace."""
    run = await service.run("aggiorna-odonimo-da-progressivo", payload.model_dump())
    return AggiornaOdonimoOutput(
        success=True,
        prognaz=payload.prognaz,
        odonimo=run.outputs.get("risultato"),
        message=COMPLETED_MESSAGE,
    )


# All fields are required for these workflows -> a single representative example.
_SOPPRIMI_ODONIMO_EXAMPLES: dict[str, Any] = {
    "default": {
        "summary": "Suppress an odonimo (its accessi are suppressed first)",
        "value": {
            "codcom": "H501",
            "denom_odonimo": "VECCHIA STRADA",
            "data_soppressione": "08/10/2024",
        },
    },
}

_SOPPRIMI_ACCESSO_EXAMPLES: dict[str, Any] = {
    "default": {
        "summary": "Suppress a single accesso by national progressive",
        "value": {
            "codcom": "H501",
            "prognaz": "2000449",
            "prognazacc": "1370588",
            "data_soppressione": "08/10/2024",
        },
    },
}

_RICERCA_EXAMPLES: dict[str, Any] = {
    "by_odonimo": {
        "summary": "Search by odonimo only (all its accessi)",
        "value": {"codcom": "H501", "denom_odonimo": "ROMA"},
    },
    "by_odonimo_and_civico": {
        "summary": "Search a specific civico",
        "value": {"codcom": "H501", "denom_odonimo": "ROMA", "numero_civico": "42"},
    },
    "by_civico_and_esponente": {
        "summary": "Search a civico with an esponente (folded into accparz)",
        "value": {
            "codcom": "H501",
            "denom_odonimo": "ROMA",
            "numero_civico": "42",
            "esponente": "A",
        },
    },
}


@router.post(
    "/sopprimi-odonimo-completo",
    response_model=SopprimiOdonimoOutput,
    summary="Suppress an odonimo and its accessi",
)
async def sopprimi_odonimo_completo(
    payload: Annotated[SopprimiOdonimoInput, Body(openapi_examples=_SOPPRIMI_ODONIMO_EXAMPLES)],
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
    "/sopprimi-accesso",
    response_model=SopprimiAccessoOutput,
    summary="Suppress a single accesso",
)
async def sopprimi_accesso(
    payload: Annotated[SopprimiAccessoInput, Body(openapi_examples=_SOPPRIMI_ACCESSO_EXAMPLES)],
    service: ServiceDep,
) -> SopprimiAccessoOutput:
    """Suppress one accesso (operation S) without touching the odonimo."""
    run = await service.run("sopprimi-accesso", payload.model_dump())
    return SopprimiAccessoOutput(
        success=True,
        esito=run.outputs.get("esito"),
        message=COMPLETED_MESSAGE,
    )


@router.post(
    "/ricerca-indirizzo-completo",
    response_model=RicercaIndirizzoOutput,
    summary="Search a complete address",
)
async def ricerca_indirizzo_completo(
    payload: Annotated[RicercaIndirizzoInput, Body(openapi_examples=_RICERCA_EXAMPLES)],
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


_RICERCA_ACCESSI_EXAMPLES: dict[str, Any] = {
    "by_civico": {
        "summary": "Filter by a civic value (accparz, required)",
        "value": {"codcom": "H501", "prognaz": "907720", "numero_civico": "1"},
    },
    "by_metrico": {
        "summary": "Filter by a metric value (accparz accepts civic or metric)",
        "value": {"codcom": "H501", "prognaz": "907720", "numero_civico": "300"},
    },
}


@router.post(
    "/ricerca-accessi-per-odonimo",
    response_model=RicercaIndirizzoOutput,
    summary="Search the accessi of an odonimo by progressive",
)
async def ricerca_accessi_per_odonimo(
    payload: Annotated[
        RicercaAccessiPerOdonimoInput, Body(openapi_examples=_RICERCA_ACCESSI_EXAMPLES)
    ],
    service: ServiceDep,
) -> RicercaIndirizzoOutput:
    """Read-only search of a specific odonimo's accessi (by prognaz; ADR 0018)."""
    run = await service.run("ricerca-accessi-per-odonimo", payload.model_dump())
    return RicercaIndirizzoOutput(
        success=True,
        odonimi=run.outputs.get("odonimi") or [],
        accessi=run.outputs.get("accessi") or [],
        message=COMPLETED_MESSAGE,
    )
