"""Input constraints mirroring the ANNCSU OAS / anncsu-sdk validation rules.

The SDK validates payloads only in its CLI layer, so nothing checks them on the
service path before the server answers with opaque errors (e.g. error 100).
The facade input models therefore enforce the documented constraints up front:
Belfiore codcom format, OAS max lengths, DD/MM/YYYY calendar dates, metodo 1-4.
"""

import pytest
from pydantic import ValidationError

from app.models.workflows import (
    AggiornaAccessoDaProgressivoInput,
    AggiornaOdonimoDaProgressivoInput,
    CreaIndirizzoCompletoInput,
    RicercaIndirizzoInput,
    SopprimiAccessoInput,
    SopprimiOdonimoInput,
)

VALID = {
    CreaIndirizzoCompletoInput: {
        "codcom": "H501",
        "denom_odonimo": "ROMA",
        "dug": "VIA",
        "numero_civico": "42",
        "data_validita": "08/10/2024",
        "sezione_censimento": "580911010001",
    },
    SopprimiOdonimoInput: {
        "codcom": "H501",
        "denom_odonimo": "ROMA",
        "data_soppressione": "08/10/2024",
    },
    RicercaIndirizzoInput: {
        "codcom": "H501",
        "denom_odonimo": "ROMA",
        "numero_civico": "42",
    },
    AggiornaAccessoDaProgressivoInput: {
        "codcom": "H501",
        "prognaz": "2000449",
        "prognazacc": "1370588",
        "numero": "42",
        "sezione_censimento": "580911010001",
    },
    SopprimiAccessoInput: {
        "codcom": "H501",
        "prognaz": "2000449",
        "prognazacc": "1370588",
        "data_soppressione": "08/10/2024",
    },
    AggiornaOdonimoDaProgressivoInput: {
        "codcom": "H501",
        "prognaz": "2000449",
        "denom_delibera": "VIA ROMA",
    },
}


@pytest.mark.parametrize("model", VALID)
def test_valid_inputs_are_accepted(model):
    assert model(**VALID[model])


@pytest.mark.parametrize(
    ("model", "field", "bad_value"),
    [
        # codcom: Belfiore format X999 (CodcomFormatError in the SDK)
        (CreaIndirizzoCompletoInput, "codcom", "h501"),
        (CreaIndirizzoCompletoInput, "codcom", "1234"),
        (CreaIndirizzoCompletoInput, "codcom", "H50"),
        (CreaIndirizzoCompletoInput, "codcom", "HH501"),
        (SopprimiOdonimoInput, "codcom", "501H"),
        (RicercaIndirizzoInput, "codcom", "h501"),
        # OAS max lengths (AccessoMaxLengthError in the SDK)
        (CreaIndirizzoCompletoInput, "numero_civico", "123456"),  # max 5
        (CreaIndirizzoCompletoInput, "sezione_censimento", "1" * 14),  # max 13
        (CreaIndirizzoCompletoInput, "denom_odonimo", "X" * 121),  # max 120
        (RicercaIndirizzoInput, "numero_civico", "123456"),
        # dates: valid DD/MM/YYYY calendar dates (InvalidDateFormatError in the SDK)
        (CreaIndirizzoCompletoInput, "data_validita", "2024-10-08"),
        (CreaIndirizzoCompletoInput, "data_validita", "31/02/2025"),
        (SopprimiOdonimoInput, "data_soppressione", "2024-10-08"),
        (SopprimiOdonimoInput, "data_soppressione", "31/02/2025"),
        (SopprimiAccessoInput, "codcom", "h501"),
        (SopprimiAccessoInput, "prognaz", "1" * 11),  # max 10
        (SopprimiAccessoInput, "prognazacc", "1" * 16),  # max 15
        (SopprimiAccessoInput, "data_soppressione", "31/02/2025"),
        # odonimo update (ADR 0013)
        (AggiornaOdonimoDaProgressivoInput, "codcom", "h501"),
        (AggiornaOdonimoDaProgressivoInput, "prognaz", "1" * 11),  # max 10
        (AggiornaOdonimoDaProgressivoInput, "denom_delibera", "X" * 121),  # max 120
        (AggiornaOdonimoDaProgressivoInput, "dug", "X" * 31),  # max 30
        (AggiornaOdonimoDaProgressivoInput, "denom_localita", "X" * 152),  # max 151
        (AggiornaOdonimoDaProgressivoInput, "codice_comunale", "X" * 31),  # max 30
        (AggiornaOdonimoDaProgressivoInput, "data_validita", "31/02/2025"),
        # generic accesso update (ADR 0010 / 0012)
        (AggiornaAccessoDaProgressivoInput, "metodo", "5"),  # survey method 1-4
        (AggiornaAccessoDaProgressivoInput, "codcom", "h501"),
        (AggiornaAccessoDaProgressivoInput, "prognaz", "1" * 11),  # max 10
        (AggiornaAccessoDaProgressivoInput, "prognazacc", "1" * 16),  # max 15
        (AggiornaAccessoDaProgressivoInput, "numero", "123456"),  # max 5
        (AggiornaAccessoDaProgressivoInput, "esponente", "X" * 16),  # max 15
        (AggiornaAccessoDaProgressivoInput, "specificita", "X" * 6),  # max 5
        (AggiornaAccessoDaProgressivoInput, "isolato", "12345"),  # max 4
        (AggiornaAccessoDaProgressivoInput, "codice_civico_comunale", "X" * 31),  # max 30
        (AggiornaAccessoDaProgressivoInput, "sezione_censimento", "1" * 14),  # max 13
        (AggiornaAccessoDaProgressivoInput, "data_validita", "31/02/2025"),
    ],
)
def test_invalid_value_is_rejected_with_the_field_named(model, field, bad_value):
    with pytest.raises(ValidationError) as excinfo:
        model(**{**VALID[model], field: bad_value})
    assert any(field in error["loc"] for error in excinfo.value.errors())


def test_accesso_update_rejects_both_numero_and_metrico():
    """Civic XOR metric: providing both is rejected (patch may omit both)."""
    with pytest.raises(ValidationError) as excinfo:
        AggiornaAccessoDaProgressivoInput(
            **{**VALID[AggiornaAccessoDaProgressivoInput], "metrico": "300"}
        )
    assert "numero" in str(excinfo.value) and "metrico" in str(excinfo.value)


def test_accesso_update_allows_neither_numero_nor_metrico():
    """Patch (ADR 0012): both may be omitted and preserved from the read."""
    payload = {**VALID[AggiornaAccessoDaProgressivoInput]}
    payload.pop("numero")
    assert AggiornaAccessoDaProgressivoInput(**payload)


def test_accesso_update_accepts_explicit_none_on_every_nullable_field():
    assert AggiornaAccessoDaProgressivoInput(
        **VALID[AggiornaAccessoDaProgressivoInput],
        metrico=None,
        esponente=None,
        specificita=None,
        isolato=None,
        codice_civico_comunale=None,
        data_validita=None,
    )


def test_accesso_update_accepts_a_metric_accesso():
    payload = {**VALID[AggiornaAccessoDaProgressivoInput]}
    payload.pop("numero")
    assert AggiornaAccessoDaProgressivoInput(**payload, metrico="300")


# --- embedded coordinates: conditional presence (OAS co-dependency rules) ---

_BASE = VALID[AggiornaAccessoDaProgressivoInput]


def test_accesso_update_accepts_complete_absence_of_coordinates():
    """Coordinates are optional: an attribute-only update needs none of x/y/z/metodo."""
    model = AggiornaAccessoDaProgressivoInput(**_BASE)
    assert model.coordinata_x is None
    assert model.coordinata_y is None
    assert model.coordinata_z is None
    assert model.metodo is None


@pytest.mark.parametrize(
    "coords",
    [
        {"coordinata_x": "13.1022000", "coordinata_y": "41.8847600"},  # x + y
        {"coordinata_x": "13.1022000", "coordinata_y": "41.8847600", "metodo": "3"},
        {
            "coordinata_x": "13.1022000",
            "coordinata_y": "41.8847600",
            "coordinata_z": "150",
            "metodo": "3",
        },
    ],
)
def test_accesso_update_accepts_well_formed_coordinate_sets(coords):
    assert AggiornaAccessoDaProgressivoInput(**_BASE, **coords)


@pytest.mark.parametrize(
    "coords",
    [
        {"coordinata_x": "13.1022000"},  # x without y
        {"coordinata_y": "41.8847600"},  # y without x
        {"coordinata_z": "150"},  # z (quota) without x/y
        {"metodo": "3"},  # metodo without x/y
        {"coordinata_z": "150", "metodo": "3"},  # z + metodo, still no x/y
    ],
)
def test_accesso_update_rejects_partial_coordinate_sets(coords):
    """x and y are co-required; z and metodo are only allowed alongside x and y."""
    with pytest.raises(ValidationError):
        AggiornaAccessoDaProgressivoInput(**_BASE, **coords)


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("coordinata_x", "not-a-number"),
        ("coordinata_x", "5.9"),  # below the Italy longitude bound
        ("coordinata_y", "35.9"),  # below the Italy latitude bound
    ],
)
def test_accesso_update_rejects_invalid_coordinate_values(field, bad_value):
    coords = {"coordinata_x": "13.1022000", "coordinata_y": "41.8847600", field: bad_value}
    with pytest.raises(ValidationError) as excinfo:
        AggiornaAccessoDaProgressivoInput(**_BASE, **coords)
    assert any(field in error["loc"] for error in excinfo.value.errors())


# --- odonimo update: administrative-object co-dependencies (ADR 0013) ---

_ODONIMO_BASE = VALID[AggiornaOdonimoDaProgressivoInput]


def _odonimo(**extra) -> AggiornaOdonimoDaProgressivoInput:
    # model_validate mirrors the JSON -> dict -> model path the route uses, so the
    # nested administrative objects (provvedimento/aut_prefettura) are coerced as dicts.
    return AggiornaOdonimoDaProgressivoInput.model_validate({**_ODONIMO_BASE, **extra})


def test_odonimo_update_accepts_minimal_input():
    assert _odonimo()


@pytest.mark.parametrize("flag", ["5", "9", "x"])
def test_odonimo_rejects_invalid_flag_delibera(flag):
    with pytest.raises(ValidationError):
        _odonimo(provvedimento={"flag_delibera": flag, "data": "01/01/2024", "protocollo": "P1"})


@pytest.mark.parametrize("flag", ["0", "1"])
def test_odonimo_flag_delibera_0_1_requires_data_and_protocollo(flag):
    with pytest.raises(ValidationError):
        _odonimo(provvedimento={"flag_delibera": flag})


def test_odonimo_flag_delibera_0_1_accepts_data_and_protocollo():
    assert _odonimo(provvedimento={"flag_delibera": "1", "data": "01/01/2024", "protocollo": "P1"})


def test_odonimo_flag_delibera_2_does_not_require_data_protocollo():
    assert _odonimo(provvedimento={"flag_delibera": "2"})


@pytest.mark.parametrize(
    "pref",
    [
        {"data_pref": "01/01/2024"},  # protocollo_pref missing
        {"protocollo_pref": "PREF1"},  # data_pref missing
    ],
)
def test_odonimo_prefettura_fields_are_co_required(pref):
    with pytest.raises(ValidationError):
        _odonimo(aut_prefettura=pref)


def test_odonimo_prefettura_accepts_both_fields():
    assert _odonimo(aut_prefettura={"data_pref": "01/01/2024", "protocollo_pref": "PREF1"})
