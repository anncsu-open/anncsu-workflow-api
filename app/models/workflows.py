"""Pydantic models for workflow inputs and outputs."""

from pydantic import BaseModel, Field

# ============================================================================
# Workflow 1: Verify and create complete address
# ============================================================================


class CreaIndirizzoCompletoInput(BaseModel):
    """Input for the complete-address creation workflow."""

    codcom: str = Field(
        ...,
        description="Codice Belfiore del comune",
        json_schema_extra={"example": "H501"},
    )
    denom_odonimo: str = Field(
        ...,
        description="Denominazione dell'odonimo",
        json_schema_extra={"example": "ROMA"},
    )
    dug: str = Field(
        ...,
        description="Denominazione Urbanistica Generica",
        json_schema_extra={"example": "VIA"},
    )
    numero_civico: str = Field(
        ..., description="Numero civico", json_schema_extra={"example": "42"}
    )
    interno: str | None = Field(
        None,
        description="Numero interno (opzionale)",
        json_schema_extra={"example": "5"},
    )
    esponente: str | None = Field(
        None,
        description="Esponente del civico",
        json_schema_extra={"example": "A"},
    )
    specificita: str | None = Field(
        None,
        description="Specificità (es. ROSSO)",
        json_schema_extra={"example": "ROSSO"},
    )
    metrico: str | None = Field(
        None,
        description="Valore metrico alternativo",
        json_schema_extra={"example": "1200"},
    )


class CreaIndirizzoCompletoOutput(BaseModel):
    """Output of the complete-address creation workflow."""

    success: bool = Field(..., description="Indica se il workflow è completato con successo")
    progressivo_nazionale_odonimo: str | None = Field(
        None, description="Progressivo nazionale dell'odonimo"
    )
    progressivo_civico: str | None = Field(None, description="Progressivo del numero civico")
    progressivo_interno: str | None = Field(None, description="Progressivo dell'interno")
    message: str = Field(..., description="Messaggio descrittivo del risultato")
    errors: list[str] | None = Field(None, description="Lista di eventuali errori")


# ============================================================================
# Workflow 2: Update access coordinates
# ============================================================================


class AggiornaCoordinateInput(BaseModel):
    """Input for the coordinate update workflow."""

    codcom: str = Field(
        ...,
        description="Codice Belfiore del comune",
        json_schema_extra={"example": "H501"},
    )
    denom_odonimo: str = Field(
        ...,
        description="Denominazione dell'odonimo",
        json_schema_extra={"example": "ROMA"},
    )
    numero_civico: str = Field(
        ..., description="Numero civico", json_schema_extra={"example": "42"}
    )
    coordinata_x: str = Field(
        ...,
        description="Longitudine WGS84 (6.0-18.0)",
        json_schema_extra={"example": "13.1022000"},
    )
    coordinata_y: str = Field(
        ...,
        description="Latitudine WGS84 (36.0-47.0)",
        json_schema_extra={"example": "41.8847600"},
    )
    coordinata_z: str | None = Field(
        None,
        description="Quota in metri (opzionale)",
        json_schema_extra={"example": "150"},
    )
    metodo: str = Field(
        "3",
        description="Metodo di rilevazione (1-4)",
        json_schema_extra={"example": "3"},
    )


class AggiornaCoordinateOutput(BaseModel):
    """Output of the coordinate update workflow."""

    success: bool = Field(..., description="Indica se il workflow è completato con successo")
    progressivo_civico: str | None = Field(None, description="Progressivo del civico aggiornato")
    coordinate: dict | None = Field(None, description="Coordinate aggiornate")
    message: str = Field(..., description="Messaggio descrittivo del risultato")
    errors: list[str] | None = Field(None, description="Lista di eventuali errori")


# ============================================================================
# Workflow 3: Suppress complete odonimo
# ============================================================================


class SopprimiOdonimoInput(BaseModel):
    """Input for the odonimo suppression workflow."""

    codcom: str = Field(
        ...,
        description="Codice Belfiore del comune",
        json_schema_extra={"example": "H501"},
    )
    denom_odonimo: str = Field(
        ...,
        description="Denominazione dell'odonimo da sopprimere",
        json_schema_extra={"example": "ROMA"},
    )
    data_soppressione: str = Field(
        ...,
        description="Data di soppressione (DD/MM/YYYY)",
        json_schema_extra={"example": "08/10/2024"},
    )


class SopprimiOdonimoOutput(BaseModel):
    """Output of the odonimo suppression workflow."""

    success: bool = Field(..., description="Indica se il workflow è completato con successo")
    odonimo_soppresso: str | None = Field(None, description="Denominazione odonimo soppresso")
    progressivo_nazionale: str | None = Field(
        None, description="Progressivo nazionale dell'odonimo soppresso"
    )
    accessi_presenti: int | None = Field(
        None, description="Numero di accessi associati all'odonimo"
    )
    message: str = Field(..., description="Messaggio descrittivo del risultato")
    errors: list[str] | None = Field(None, description="Lista di eventuali errori")


# ============================================================================
# Workflow 4: Search complete address
# ============================================================================


class RicercaIndirizzoInput(BaseModel):
    """Input for the address search workflow."""

    codcom: str = Field(
        ...,
        description="Codice Belfiore del comune",
        json_schema_extra={"example": "H501"},
    )
    denom_odonimo: str = Field(
        ...,
        description="Denominazione dell'odonimo (anche parziale)",
        json_schema_extra={"example": "ROMA"},
    )
    numero_civico: str | None = Field(
        None,
        description="Numero civico (opzionale)",
        json_schema_extra={"example": "42"},
    )


class OdonimoResult(BaseModel):
    """Odonimo search result."""

    prognaz: str = Field(..., description="Progressivo nazionale")
    dug: str = Field(..., description="Denominazione Urbanistica Generica")
    denomuff: str = Field(..., description="Denominazione ufficiale")
    denomloc: str | None = Field(None, description="Denominazione località")
    denomlingua1: str | None = Field(None, description="Denominazione in lingua 1")
    denomlingua2: str | None = Field(None, description="Denominazione in lingua 2")


class AccessoResult(BaseModel):
    """Accesso search result."""

    prognazacc: str = Field(..., description="Progressivo nazionale accesso")
    civico: str | None = Field(None, description="Numero civico")
    esp: str | None = Field(None, description="Esponente")
    specif: str | None = Field(None, description="Specificità")
    metrico: str | None = Field(None, description="Valore metrico")
    # coordX and coordY use mixedCase to mirror the ANNCSU OpenAPI specs exactly
    coordX: str | None = Field(None, description="Coordinata X")  # noqa: N815
    coordY: str | None = Field(None, description="Coordinata Y")  # noqa: N815
    quota: str | None = Field(None, description="Quota")
    metodo: str | None = Field(None, description="Metodo di rilevazione")


class RicercaIndirizzoOutput(BaseModel):
    """Output of the address search workflow."""

    success: bool = Field(..., description="Indica se la ricerca è completata con successo")
    odonimi: list[OdonimoResult] = Field(default_factory=list, description="Lista odonimi trovati")
    accessi: list[AccessoResult] = Field(default_factory=list, description="Lista accessi trovati")
    message: str = Field(..., description="Messaggio descrittivo del risultato")
    errors: list[str] | None = Field(None, description="Lista di eventuali errori")
