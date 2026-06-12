"""The operationId registry (decision D2: typed SDK methods per operation).

Maps every ``sourceName.operationId`` the canonical Arazzo spec references to a
dotted method path on that source's sub-SDK client. Going through the typed SDK
methods (rather than raw requests) keeps PDND auth, payload validation, and the
generated models in play. The registry is the single place spec and SDK meet;
``tests/adapters/test_registry.py`` pins both directions.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import reduce
from typing import Any


class UnknownOperationError(Exception):
    """A dispatched ``operationId`` has no registered SDK method."""


@dataclass(frozen=True)
class Operation:
    """Where an Arazzo operation lives on the SDK."""

    source: str  # Arazzo sourceDescription name, e.g. "anncsu-consultazione"
    method_path: str  # dotted attribute path on that source's client


OPERATION_REGISTRY: dict[str, Operation] = {
    "anncsu-consultazione.esisteOdonimoPost": Operation(
        "anncsu-consultazione", "json_post.esiste_odonimo_post"
    ),
    "anncsu-consultazione.esisteAccessoPost": Operation(
        "anncsu-consultazione", "json_post.esiste_accesso_post"
    ),
    "anncsu-consultazione.elencoodonimiprogPost": Operation(
        "anncsu-consultazione", "json_post.elencoodonimiprog_post"
    ),
    "anncsu-consultazione.elencoaccessiprogPost": Operation(
        "anncsu-consultazione", "json_post.elencoaccessiprog_post"
    ),
    "anncsu-odonimi.gestioneAnncsuOdonimiPdnd": Operation(
        "anncsu-odonimi", "anncsu.gestione_anncsu_odonimi_pdnd"
    ),
    "anncsu-accessi.gestioneAnncsuPdnd": Operation("anncsu-accessi", "anncsu.gestione_anncsu_pdnd"),
    "anncsu-coordinate.gestionecoordinate": Operation(
        "anncsu-coordinate", "json_post.gestionecoordinate"
    ),
}


def operation_for(operation_id: str) -> Operation:
    """Look up ``operation_id`` or raise :class:`UnknownOperationError`."""
    try:
        return OPERATION_REGISTRY[operation_id]
    except KeyError:
        raise UnknownOperationError(
            f"operationId {operation_id!r} is not registered for any SDK method"
        ) from None


def resolve_method(client: Any, method_path: str) -> Any:
    """Resolve a dotted ``method_path`` (e.g. ``json_post.esiste_odonimo_post``)."""
    return reduce(getattr, method_path.split("."), client)
