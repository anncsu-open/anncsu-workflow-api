"""Pydantic models for workflow inputs and outputs.

Field descriptions are the English baseline; other languages are overlaid onto the
OpenAPI document from ``app/i18n/locales/<lang>.json`` (see ADR 0005). ANNCSU domain
terms (odonimo, accesso, civico, codcom, …) are kept as-is.
"""

from pydantic import BaseModel, Field

# ============================================================================
# Shared search-result models
# ============================================================================


class OdonimoResult(BaseModel):
    """Odonimo search result."""

    prognaz: str = Field(..., description="National progressive number")
    dug: str = Field(..., description="Generic urban denomination (DUG)")
    denomuff: str = Field(..., description="Official denomination")
    denomloc: str | None = Field(None, description="Locality denomination")
    denomlingua1: str | None = Field(None, description="Denomination in language 1")
    denomlingua2: str | None = Field(None, description="Denomination in language 2")


class AccessoResult(BaseModel):
    """Accesso search result."""

    prognazacc: str = Field(..., description="National progressive number of the accesso")
    civico: str | None = Field(None, description="Civico (street number)")
    esp: str | None = Field(None, description="Esponente")
    specif: str | None = Field(None, description="Specificità")
    metrico: str | None = Field(None, description="Metric value")
    # coordX and coordY use mixedCase to mirror the ANNCSU OpenAPI specs exactly
    coordX: str | None = Field(None, description="X coordinate")  # noqa: N815
    coordY: str | None = Field(None, description="Y coordinate")  # noqa: N815
    quota: str | None = Field(None, description="Elevation")
    metodo: str | None = Field(None, description="Survey method")


# ============================================================================
# Workflow 1: Verify and create complete address
# ============================================================================


class CreaIndirizzoCompletoInput(BaseModel):
    """Input for the complete-address creation workflow."""

    codcom: str = Field(
        ...,
        description="Belfiore municipality code (codcom)",
        json_schema_extra={"example": "H501"},
    )
    denom_odonimo: str = Field(
        ...,
        description="Odonimo denomination",
        json_schema_extra={"example": "ROMA"},
    )
    dug: str = Field(
        ...,
        description="Generic urban denomination (DUG)",
        json_schema_extra={"example": "VIA"},
    )
    numero_civico: str = Field(
        ..., description="Civico (street number)", json_schema_extra={"example": "42"}
    )
    data_validita: str | None = Field(
        None,
        description="Administrative validity date (DD/MM/YYYY) for creations",
        json_schema_extra={"example": "08/10/2024"},
    )
    sezione_censimento: str = Field(
        ...,
        max_length=13,
        description=(
            "Census section of the accesso (ISTAT SEZ21_ID format), required when "
            "the accesso is created; not derivable from the consultation APIs"
        ),
        json_schema_extra={"example": "580911010001"},
    )


class CreaIndirizzoCompletoOutput(BaseModel):
    """Output of the complete-address creation workflow."""

    success: bool = Field(..., description="Whether the workflow completed successfully")
    progressivo_nazionale_odonimo: str | None = Field(
        None, description="National progressive number of the odonimo"
    )
    progressivo_civico: str | None = Field(None, description="Progressive number of the civico")
    message: str = Field(..., description="Descriptive message of the result")
    errors: list[str] | None = Field(None, description="List of any errors")


# ============================================================================
# Workflow 2: Update access coordinates
# ============================================================================


class AggiornaCoordinateInput(BaseModel):
    """Input for the coordinate update workflow."""

    codcom: str = Field(
        ...,
        description="Belfiore municipality code (codcom)",
        json_schema_extra={"example": "H501"},
    )
    denom_odonimo: str = Field(
        ...,
        description="Odonimo denomination",
        json_schema_extra={"example": "ROMA"},
    )
    numero_civico: str = Field(
        ..., description="Civico (street number)", json_schema_extra={"example": "42"}
    )
    coordinata_x: str = Field(
        ...,
        description="Longitude WGS84 (6.0-18.0)",
        json_schema_extra={"example": "13.1022000"},
    )
    coordinata_y: str = Field(
        ...,
        description="Latitude WGS84 (36.0-47.0)",
        json_schema_extra={"example": "41.8847600"},
    )
    coordinata_z: str | None = Field(
        None,
        description="Elevation in meters (optional)",
        json_schema_extra={"example": "150"},
    )
    metodo: str = Field(
        "3",
        description="Survey method (1-4)",
        json_schema_extra={"example": "3"},
    )


class AggiornaCoordinateDaProgressivoAccessoInput(BaseModel):
    """Input for the coordinate update workflow addressing the accesso directly.

    The accesso is identified by its national progressive (``prognazacc``, as the
    consultation APIs return it): no denomination resolution, one upstream call.
    """

    codcom: str = Field(
        ...,
        description="Belfiore municipality code (codcom)",
        json_schema_extra={"example": "H501"},
    )
    prognazacc: str = Field(
        ...,
        description="National progressive number of the accesso",
        json_schema_extra={"example": "1370588"},
    )
    coordinata_x: str = Field(
        ...,
        description="Longitude WGS84 (6.0-18.0)",
        json_schema_extra={"example": "13.1022000"},
    )
    coordinata_y: str = Field(
        ...,
        description="Latitude WGS84 (36.0-47.0)",
        json_schema_extra={"example": "41.8847600"},
    )
    coordinata_z: str | None = Field(
        None,
        description="Elevation in meters (optional)",
        json_schema_extra={"example": "150"},
    )
    metodo: str = Field(
        "3",
        description="Survey method (1-4)",
        json_schema_extra={"example": "3"},
    )


class AggiornaCoordinateOutput(BaseModel):
    """Output of the coordinate update workflow."""

    success: bool = Field(..., description="Whether the workflow completed successfully")
    progressivo_civico: str | None = Field(
        None, description="Progressive number of the updated civico"
    )
    coordinate: dict | None = Field(None, description="Updated coordinates")
    message: str = Field(..., description="Descriptive message of the result")
    errors: list[str] | None = Field(None, description="List of any errors")


# ============================================================================
# Workflow 3: Suppress complete odonimo
# ============================================================================


class SopprimiOdonimoInput(BaseModel):
    """Input for the odonimo suppression workflow."""

    codcom: str = Field(
        ...,
        description="Belfiore municipality code (codcom)",
        json_schema_extra={"example": "H501"},
    )
    denom_odonimo: str = Field(
        ...,
        description="Denomination of the odonimo to suppress",
        json_schema_extra={"example": "ROMA"},
    )
    data_soppressione: str = Field(
        ...,
        description="Suppression date (DD/MM/YYYY)",
        json_schema_extra={"example": "08/10/2024"},
    )


class SopprimiOdonimoOutput(BaseModel):
    """Output of the odonimo suppression workflow."""

    success: bool = Field(..., description="Whether the workflow completed successfully")
    odonimo_soppresso: str | None = Field(
        None, description="Denomination of the suppressed odonimo"
    )
    progressivo_nazionale: str | None = Field(
        None, description="National progressive number of the suppressed odonimo"
    )
    accessi_presenti: list[AccessoResult] | None = Field(
        None, description="Accessi associated with the odonimo (suppressed before the odonimo)"
    )
    message: str = Field(..., description="Descriptive message of the result")
    errors: list[str] | None = Field(None, description="List of any errors")


# ============================================================================
# Workflow 4: Search complete address
# ============================================================================


class RicercaIndirizzoInput(BaseModel):
    """Input for the address search workflow."""

    codcom: str = Field(
        ...,
        description="Belfiore municipality code (codcom)",
        json_schema_extra={"example": "H501"},
    )
    denom_odonimo: str = Field(
        ...,
        description="Odonimo denomination (partial allowed)",
        json_schema_extra={"example": "ROMA"},
    )
    numero_civico: str | None = Field(
        None,
        description="Civico (street number, optional)",
        json_schema_extra={"example": "42"},
    )


class RicercaIndirizzoOutput(BaseModel):
    """Output of the address search workflow."""

    success: bool = Field(..., description="Whether the search completed successfully")
    odonimi: list[OdonimoResult] = Field(default_factory=list, description="List of odonimi found")
    accessi: list[AccessoResult] = Field(default_factory=list, description="List of accessi found")
    message: str = Field(..., description="Descriptive message of the result")
    errors: list[str] | None = Field(None, description="List of any errors")
