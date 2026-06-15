"""Pydantic models for workflow inputs and outputs.

Field descriptions are the English baseline; other languages are overlaid onto the
OpenAPI document from ``app/i18n/locales/<lang>.json`` (see ADR 0005). ANNCSU domain
terms (odonimo, accesso, civico, codcom, …) are kept as-is.

Input constraints mirror the ANNCSU OpenAPI / anncsu-sdk validation rules
(Belfiore codcom format, OAS max lengths, DD/MM/YYYY dates, metodo 1-4): the SDK
validates only in its CLI layer, so the facade rejects bad input up front with a
named field instead of surfacing an opaque server error mid-workflow.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field, field_validator, model_validator

# Belfiore municipality code: one uppercase letter + three digits (e.g. H501).
CODCOM_PATTERN = r"^[A-Z][0-9]{3}$"
# Survey method for coordinates, per the coordinate OpenAPI.
METODO_PATTERN = r"^[1-4]$"


def _wgs84(low: float, high: float):
    """Validator for a WGS84 coordinate string within the Italy bounds (or None)."""

    def validate(value: str | None) -> str | None:
        if value is None:
            return value
        try:
            number = float(value)
        except ValueError as error:
            raise ValueError("must be a decimal number") from error
        if not low <= number <= high:
            raise ValueError(f"must be within {low} and {high} (Italy bounds)")
        return value

    return validate


def _ddmmyyyy(value: str | None) -> str | None:
    """Accept only valid DD/MM/YYYY calendar dates (or None)."""
    if value is None:
        return value
    try:
        datetime.strptime(value, "%d/%m/%Y")  # noqa: DTZ007 - date only, no tz involved
    except ValueError as error:
        raise ValueError("must be a valid DD/MM/YYYY date") from error
    return value


def _ddmmyyyy_not_future(value: str | None) -> str | None:
    """A DD/MM/YYYY date that is not in the future (odonimi rule: data_valid_amm)."""
    value = _ddmmyyyy(value)
    if value is not None:
        parsed = datetime.strptime(value, "%d/%m/%Y").date()  # noqa: DTZ007 - format pre-validated
        if parsed > datetime.now(UTC).date():
            raise ValueError("must not be in the future")
    return value


# ============================================================================
# Shared search-result models
# ============================================================================


class OdonimoResult(BaseModel):
    """Odonimo search result.

    Fields are optional (a search result should not fail to map on an unusual
    item). The real API returns the wire name ``duf`` — not the OAS ``denomuff`` —
    and the extra ``cododocomunale`` (anncsu-sdk#12); the transport emits the wire
    names (``model_dump(by_alias=True)``), so these mirror them.
    """

    prognaz: str = Field(..., description="National progressive number")
    dug: str | None = Field(None, description="Generic urban denomination (DUG)")
    duf: str | None = Field(
        None, description="Official denomination (denominazione urbanistica ufficiale)"
    )
    cododocomunale: str | None = Field(None, description="Municipal street code")
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
    codacccomunale: str | None = Field(None, description="Municipal access code")


# ============================================================================
# Workflow 1: Verify and create complete address
# ============================================================================


class CreaIndirizzoCompletoInput(BaseModel):
    """Input for the complete-address creation workflow (ADR 0016).

    Exposes the full accesso and odonimo creation fields. The accesso is identified
    by exactly one of ``numero_civico`` (civic) or ``metrico`` (metric); everything
    beyond the required core is optional and the executor prunes unset fields.
    """

    codcom: str = Field(
        ...,
        pattern=CODCOM_PATTERN,
        description="Belfiore municipality code (codcom)",
        json_schema_extra={"example": "H501"},
    )
    denom_odonimo: str = Field(
        ...,
        max_length=120,
        description="Odonimo denomination",
        json_schema_extra={"example": "ROMA"},
    )
    dug: str = Field(
        ...,
        max_length=30,
        description="Generic urban denomination (DUG)",
        json_schema_extra={"example": "VIA"},
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

    # Accesso identifier: exactly one of numero_civico (civic) or metrico (metric).
    numero_civico: str | None = Field(
        None,
        max_length=5,
        description="Civico (street number); mutually exclusive with metrico",
        json_schema_extra={"example": "42"},
    )
    metrico: str | None = Field(
        None,
        max_length=6,
        description="Metric identification; mutually exclusive with numero_civico",
        json_schema_extra={"example": "300"},
    )

    # Accesso optional attributes.
    esponente: str | None = Field(
        None, max_length=15, description="Esponente", json_schema_extra={"example": "A"}
    )
    specificita: str | None = Field(
        None, max_length=5, description="Specificità", json_schema_extra={"example": "ROSSO"}
    )
    isolato: str | None = Field(
        None, max_length=4, description="Isolato code", json_schema_extra={"example": "12"}
    )
    codice_civico_comunale: str | None = Field(
        None,
        max_length=30,
        description="Municipal code of the accesso",
        json_schema_extra={"example": "7569A"},
    )

    # Accesso coordinates (optional, co-dependent: x with y; z/metodo only with x and y).
    coordinata_x: str | None = Field(
        None,
        max_length=12,
        description="Longitude WGS84 (6.0-18.0); requires coordinata_y",
        json_schema_extra={"example": "13.1022000"},
    )
    coordinata_y: str | None = Field(
        None,
        max_length=12,
        description="Latitude WGS84 (36.0-47.0); requires coordinata_x",
        json_schema_extra={"example": "41.8847600"},
    )
    coordinata_z: str | None = Field(
        None,
        max_length=7,
        description="Elevation in meters; only with coordinata_x and coordinata_y",
        json_schema_extra={"example": "150"},
    )
    metodo: str | None = Field(
        None,
        pattern=METODO_PATTERN,
        description="Survey method (1-4); only with coordinata_x and coordinata_y",
        json_schema_extra={"example": "3"},
    )

    # Odonimo optional metadata (denom_delibera/provvedimento default below for create).
    denom_localita: str | None = Field(
        None,
        max_length=151,
        description="Locality denomination",
        json_schema_extra={"example": "CENTRO"},
    )
    denom_in_lingua_1: str | None = Field(
        None, max_length=150, description="Denomination in language 1"
    )
    denom_in_lingua_2: str | None = Field(
        None, max_length=150, description="Denomination in language 2"
    )
    codice_comunale: str | None = Field(
        None, max_length=30, description="Municipal code of the odonimo"
    )
    denom_delibera: str | None = Field(
        None,
        max_length=120,
        description="Odonimo denomination from the delibera; defaults to denom_odonimo when omitted",
        json_schema_extra={"example": "VIA ROMA"},
    )
    provvedimento: Provvedimento | None = Field(
        None, description="Authorizing delibera; defaults to flag_delibera '2' when omitted"
    )
    aut_prefettura: AutPrefettura | None = Field(None, description="Prefecture authorization")

    data_validita: str | None = Field(
        None,
        description="Administrative validity date (DD/MM/YYYY) for creations, not in the future",
        json_schema_extra={"example": "08/10/2024"},
    )

    # The odonimo branch forbids a future data_valid_amm; harmless for the accesso branch.
    _data_validita_not_future = field_validator("data_validita")(_ddmmyyyy_not_future)
    _x_is_in_italy = field_validator("coordinata_x")(_wgs84(6.0, 18.0))
    _y_is_in_italy = field_validator("coordinata_y")(_wgs84(36.0, 47.0))

    @model_validator(mode="after")
    def _exactly_one_accesso_identifier(self) -> CreaIndirizzoCompletoInput:
        # On create an accesso needs an identifier: exactly one of numero/metrico.
        if (self.numero_civico is None) == (self.metrico is None):
            raise ValueError("exactly one of 'numero_civico' or 'metrico' must be provided")
        return self

    @model_validator(mode="after")
    def _coordinates_are_consistent(self) -> CreaIndirizzoCompletoInput:
        if (self.coordinata_x is None) != (self.coordinata_y is None):
            raise ValueError("coordinata_x and coordinata_y must be provided together")
        if (self.coordinata_z is not None or self.metodo is not None) and self.coordinata_x is None:
            raise ValueError(
                "coordinata_z and metodo are only allowed with coordinata_x and coordinata_y"
            )
        return self

    @model_validator(mode="after")
    def _apply_creation_defaults(self) -> CreaIndirizzoCompletoInput:
        # Backward compat: the create historically sent the odonimo denomination as
        # the delibera with flag_delibera "2"; preserve that when not provided.
        if self.denom_delibera is None:
            self.denom_delibera = self.denom_odonimo
        if self.provvedimento is None:
            self.provvedimento = Provvedimento(flag_delibera="2")
        return self


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
# Workflow: Generic accesso update by national progressives (ADR 0010)
# ============================================================================


class AggiornaAccessoDaProgressivoInput(BaseModel):
    """Input for the generic accesso update (ANNCSU operation R).

    Replace semantics: the request describes the accesso's NEW state; attributes
    left out are not guaranteed to be preserved. To update a single attribute,
    read the accesso first and send the full desired state back.
    """

    codcom: str = Field(
        ...,
        pattern=CODCOM_PATTERN,
        description="Belfiore municipality code (codcom)",
        json_schema_extra={"example": "H501"},
    )
    prognaz: str = Field(
        ...,
        max_length=10,
        description="National progressive number of the odonimo",
        json_schema_extra={"example": "2000449"},
    )
    prognazacc: str = Field(
        ...,
        max_length=15,
        description="National progressive number of the accesso",
        json_schema_extra={"example": "1370588"},
    )
    numero: str | None = Field(
        None,
        max_length=5,
        description="Civico (street number); mutually exclusive with metrico",
        json_schema_extra={"example": "42"},
    )
    metrico: str | None = Field(
        None,
        max_length=6,
        description="Metric identification; mutually exclusive with numero",
        json_schema_extra={"example": "300"},
    )
    esponente: str | None = Field(
        None, max_length=15, description="Esponente", json_schema_extra={"example": "A"}
    )
    specificita: str | None = Field(
        None, max_length=5, description="Specificità", json_schema_extra={"example": "ROSSO"}
    )
    isolato: str | None = Field(
        None, max_length=4, description="Isolato code", json_schema_extra={"example": "12"}
    )
    codice_civico_comunale: str | None = Field(
        None,
        max_length=30,
        description="Municipal code of the accesso",
        json_schema_extra={"example": "7569A"},
    )
    sezione_censimento: str = Field(
        ...,
        max_length=13,
        description=(
            "Census section of the accesso (ISTAT SEZ21_ID format); "
            "not derivable from the consultation APIs"
        ),
        json_schema_extra={"example": "580911010001"},
    )
    data_validita: str | None = Field(
        None,
        description="Administrative validity date (DD/MM/YYYY)",
        json_schema_extra={"example": "08/10/2024"},
    )
    # Coordinates are part of the accesso's state: under replace semantics they
    # must be settable here (and re-sent) or an attribute update would drop them.
    # Optional, but co-dependent (see the validator): x and y go together, and
    # z/metodo only alongside x and y.
    coordinata_x: str | None = Field(
        None,
        max_length=12,
        description="Longitude WGS84 (6.0-18.0); requires coordinata_y",
        json_schema_extra={"example": "13.1022000"},
    )
    coordinata_y: str | None = Field(
        None,
        max_length=12,
        description="Latitude WGS84 (36.0-47.0); requires coordinata_x",
        json_schema_extra={"example": "41.8847600"},
    )
    coordinata_z: str | None = Field(
        None,
        max_length=7,
        description="Elevation in meters; only with coordinata_x and coordinata_y",
        json_schema_extra={"example": "150"},
    )
    metodo: str | None = Field(
        None,
        pattern=METODO_PATTERN,
        description="Survey method (1-4); only with coordinata_x and coordinata_y",
        json_schema_extra={"example": "3"},
    )

    _data_validita_is_a_date = field_validator("data_validita")(_ddmmyyyy)
    _x_is_in_italy = field_validator("coordinata_x")(_wgs84(6.0, 18.0))
    _y_is_in_italy = field_validator("coordinata_y")(_wgs84(36.0, 47.0))

    @model_validator(mode="after")
    def _at_most_one_of_numero_or_metrico(self) -> AggiornaAccessoDaProgressivoInput:
        # Patch semantics: either may be omitted (preserved from the read); they
        # are mutually exclusive only when both are provided.
        if self.numero is not None and self.metrico is not None:
            raise ValueError(
                "'numero' and 'metrico' are mutually exclusive "
                "(an accesso is identified by civic number XOR metric system)"
            )
        return self

    @model_validator(mode="after")
    def _coordinates_are_consistent(self) -> AggiornaAccessoDaProgressivoInput:
        if (self.coordinata_x is None) != (self.coordinata_y is None):
            raise ValueError("coordinata_x and coordinata_y must be provided together")
        if (self.coordinata_z is not None or self.metodo is not None) and self.coordinata_x is None:
            raise ValueError(
                "coordinata_z and metodo are only allowed with coordinata_x and coordinata_y"
            )
        return self


class AggiornaAccessoOutput(BaseModel):
    """Output of the generic accesso update workflow."""

    success: bool = Field(..., description="Whether the workflow completed successfully")
    prognazacc: str | None = Field(
        None, description="National progressive number of the updated accesso"
    )
    accesso: dict | None = Field(None, description="Accesso state returned by ANNCSU")
    message: str = Field(..., description="Descriptive message of the result")
    errors: list[str] | None = Field(None, description="List of any errors")


# ============================================================================
# Workflow: Generic odonimo update by national progressive (ADR 0013)
# ============================================================================

# flag_delibera 0..4; values 0 and 1 require the delibera's data + protocollo.
FLAG_DELIBERA_PATTERN = r"^[0-4]$"
_FLAG_DELIBERA_NEEDS_DETAILS = {"0", "1"}


class Provvedimento(BaseModel):
    """The administrative act (delibera) authorizing the odonimo."""

    flag_delibera: str | None = Field(
        None,
        pattern=FLAG_DELIBERA_PATTERN,
        description="Delibera flag (0-4); 0 and 1 require data and protocollo",
        json_schema_extra={"example": "2"},
    )
    data: str | None = Field(
        None, description="Delibera date (DD/MM/YYYY)", json_schema_extra={"example": "01/01/2024"}
    )
    protocollo: str | None = Field(
        None, description="Delibera protocol", json_schema_extra={"example": "PROT/123"}
    )

    _data_is_a_date = field_validator("data")(_ddmmyyyy)

    @model_validator(mode="after")
    def _flag_0_1_requires_details(self) -> Provvedimento:
        if self.flag_delibera in _FLAG_DELIBERA_NEEDS_DETAILS and (
            self.data is None or self.protocollo is None
        ):
            raise ValueError(
                f"provvedimento.data and provvedimento.protocollo are required "
                f"when flag_delibera is {self.flag_delibera!r}"
            )
        return self


class AutPrefettura(BaseModel):
    """Prefecture authorization; its two fields are co-required."""

    data_pref: str | None = Field(
        None,
        description="Prefecture date (DD/MM/YYYY)",
        json_schema_extra={"example": "01/01/2024"},
    )
    protocollo_pref: str | None = Field(
        None, description="Prefecture protocol", json_schema_extra={"example": "PREF/1"}
    )

    _data_pref_is_a_date = field_validator("data_pref")(_ddmmyyyy)

    @model_validator(mode="after")
    def _both_or_neither(self) -> AutPrefettura:
        if (self.data_pref is None) != (self.protocollo_pref is None):
            raise ValueError("data_pref and protocollo_pref must be provided together")
        return self


# CreaIndirizzoCompletoInput references Provvedimento/AutPrefettura (defined above,
# after it in the file), so resolve those forward references now.
CreaIndirizzoCompletoInput.model_rebuild()


class AggiornaOdonimoDaProgressivoInput(BaseModel):
    """Input for the odonimo update (ANNCSU operation R), by national progressive.

    Patch via read-modify-write: fields left out are preserved from the read.
    ``denom_delibera`` is the odonimo's denomination and is not exposed by the
    consultation, so it is required (ADR 0013).
    """

    codcom: str = Field(
        ...,
        pattern=CODCOM_PATTERN,
        description="Belfiore municipality code (codcom)",
        json_schema_extra={"example": "H501"},
    )
    prognaz: str = Field(
        ...,
        max_length=10,
        description="National progressive number of the odonimo",
        json_schema_extra={"example": "2000449"},
    )
    denom_delibera: str = Field(
        ...,
        max_length=120,
        description="Odonimo denomination from the delibera; not derivable from consultation",
        json_schema_extra={"example": "VIA ROMA"},
    )
    dug: str | None = Field(
        None,
        max_length=30,
        description="Generic urban denomination (preserved from the read if omitted)",
        json_schema_extra={"example": "VIA"},
    )
    denom_localita: str | None = Field(
        None,
        max_length=151,
        description="Locality denomination",
        json_schema_extra={"example": "CENTRO"},
    )
    denom_in_lingua_1: str | None = Field(
        None, max_length=150, description="Denomination in language 1"
    )
    denom_in_lingua_2: str | None = Field(
        None, max_length=150, description="Denomination in language 2"
    )
    codice_comunale: str | None = Field(
        None, max_length=30, description="Municipal code of the odonimo"
    )
    provvedimento: Provvedimento | None = Field(None, description="Authorizing delibera")
    aut_prefettura: AutPrefettura | None = Field(None, description="Prefecture authorization")
    data_validita: str | None = Field(
        None,
        description="Administrative validity date (DD/MM/YYYY), not in the future",
        json_schema_extra={"example": "08/10/2024"},
    )

    # ANNCSU forbids a future data_valid_amm for odonimi (unlike accessi).
    _data_validita_not_future = field_validator("data_validita")(_ddmmyyyy_not_future)


class AggiornaOdonimoOutput(BaseModel):
    """Output of the odonimo update workflow."""

    success: bool = Field(..., description="Whether the workflow completed successfully")
    prognaz: str | None = Field(None, description="National progressive number of the odonimo")
    odonimo: dict | None = Field(None, description="Odonimo state returned by ANNCSU")
    message: str = Field(..., description="Descriptive message of the result")
    errors: list[str] | None = Field(None, description="List of any errors")


# ============================================================================
# Workflow 3: Suppress complete odonimo
# ============================================================================


class SopprimiOdonimoInput(BaseModel):
    """Input for the odonimo suppression workflow."""

    codcom: str = Field(
        ...,
        pattern=CODCOM_PATTERN,
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

    _data_soppressione_is_a_date = field_validator("data_soppressione")(_ddmmyyyy)


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
        pattern=CODCOM_PATTERN,
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
        max_length=5,
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


class RicercaAccessiPerOdonimoInput(BaseModel):
    """Input for the by-prognaz access search workflow (ADR 0018)."""

    codcom: str = Field(
        ...,
        pattern=CODCOM_PATTERN,
        description="Belfiore municipality code (codcom)",
        json_schema_extra={"example": "H501"},
    )
    prognaz: str = Field(
        ...,
        description="National progressive number of the odonimo (prognaz)",
        json_schema_extra={"example": "907720"},
    )
    # Maps to ANNCSU's `accparz`, which the API requires and which accepts a civic
    # OR a metric value (partial allowed). It is mandatory here (no magic default,
    # ADR 0018) and not constrained to the civic length used elsewhere.
    numero_civico: str = Field(
        ...,
        min_length=1,
        description="Civic or metric value (accparz), partial allowed (required)",
        json_schema_extra={"example": "1"},
    )


# ============================================================================
# Workflow: Suppress a single accesso
# ============================================================================


class SopprimiAccessoInput(BaseModel):
    """Input for the single-accesso suppression workflow.

    A dated logical suppression (ANNCSU operation S), addressed by the odonimo and
    accesso national progressives — removes one civico without touching the odonimo.
    """

    codcom: str = Field(
        ...,
        pattern=CODCOM_PATTERN,
        description="Belfiore municipality code (codcom)",
        json_schema_extra={"example": "H501"},
    )
    prognaz: str = Field(
        ...,
        max_length=10,
        description="National progressive number of the odonimo",
        json_schema_extra={"example": "2000449"},
    )
    prognazacc: str = Field(
        ...,
        max_length=15,
        description="National progressive number of the accesso to suppress",
        json_schema_extra={"example": "1370588"},
    )
    data_soppressione: str = Field(
        ...,
        description="Suppression date (DD/MM/YYYY)",
        json_schema_extra={"example": "08/10/2024"},
    )

    _data_soppressione_is_a_date = field_validator("data_soppressione")(_ddmmyyyy)


class SopprimiAccessoOutput(BaseModel):
    """Output of the single-accesso suppression workflow."""

    success: bool = Field(..., description="Whether the workflow completed successfully")
    esito: str | None = Field(None, description="ANNCSU outcome code (esito)")
    message: str = Field(..., description="Descriptive message of the result")
    errors: list[str] | None = Field(None, description="List of any errors")
